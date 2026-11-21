import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import text
from tests.factories import create_meme, create_meme_source, create_user, create_user_language

from src.broadcasts import exploration as ex
from src.database import engine, fetch_one
from src.storage.schemas import MemeData

USER = 9017101
OLD = 9017102
CHOSEN = 9017103


@pytest_asyncio.fixture
async def opportunity_user(monkeypatch):
    monkeypatch.setattr(ex.settings, "DORMANT_PUSH_EXPLORATION_ENABLED", True)
    monkeypatch.setattr(ex.settings, "BROADCAST_HIGH_QUALITY_PICK_ENABLED", True)
    monkeypatch.setattr(ex.settings, "BROADCAST_CADENCE_HOLDOUT_ENABLED", True)
    async with engine.begin() as conn:
        await create_user(conn, USER)
        await create_user_language(conn, USER)
        await create_meme_source(conn, OLD)
        await create_meme(conn, OLD, OLD)
        await create_meme(conn, CHOSEN, OLD)
        await conn.execute(
            text(
                "UPDATE \"user\" SET last_active_at = timezone('UTC', now()) "
                "- interval '7 days 30 minutes' WHERE id = :id"
            ),
            {"id": USER},
        )
        await conn.execute(
            text(
                "INSERT INTO user_meme_reaction "
                "(user_id,meme_id,reaction_id,reacted_at,recommended_by,sent_at) "
                "VALUES (:user,:meme,1,timezone('UTC',now()) "
                "- interval '7 days 30 minutes','feed', "
                "timezone('UTC',now()) - interval '8 days')"
            ),
            {"user": USER, "meme": OLD},
        )
        await conn.execute(
            text(
                "UPDATE push_content_control SET enabled=true, pause_reason=NULL, "
                "ends_at=timezone('UTC',now())+interval '1 day'"
            )
        )
    yield
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM user_meme_reaction WHERE user_id=:id"), {"id": USER})
        await conn.execute(text('DELETE FROM "user" WHERE id=:id'), {"id": USER})
        await conn.execute(
            text("DELETE FROM meme WHERE id IN (:old,:chosen)"), {"old": OLD, "chosen": CHOSEN}
        )
        await conn.execute(text("DELETE FROM meme_source WHERE id=:id"), {"id": OLD})
        await conn.execute(
            text(
                "UPDATE push_content_control SET enabled=true, pause_reason=NULL, "
                "ends_at='2027-01-17'"
            )
        )


@pytest.mark.asyncio
async def test_concurrent_reservation_and_switch_never_reclaim(opportunity_user):
    rows = await asyncio.gather(
        ex.reserve_opportunity(USER, True), ex.reserve_opportunity(USER, True)
    )
    assert sum(row is not None for row in rows) == 1
    row = next(row for row in rows if row)
    assert row["enrolled"]
    assert row["variant"] == ex.content_variant(USER)
    await ex.pause_experiment("test")
    assert await ex.reserve_opportunity(USER, True) is None


@pytest.mark.parametrize("case", ["disabled", "ended", "cap", "admin"])
@pytest.mark.asyncio
async def test_closed_enrollment_uses_hq_without_assignment(opportunity_user, monkeypatch, case):
    if case == "disabled":
        monkeypatch.setattr(ex.settings, "DORMANT_PUSH_EXPLORATION_ENABLED", False)
    async with engine.begin() as conn:
        if case == "ended":
            await conn.execute(
                text("UPDATE push_content_control SET ends_at=timezone('UTC',now())")
            )
        if case == "admin":
            await conn.execute(text("UPDATE \"user\" SET type='admin' WHERE id=:id"), {"id": USER})
    row = await ex.reserve_opportunity(USER, case != "cap")
    assert row["variant"] == "hq" and not row["enrolled"]
    assert (
        await fetch_one(
            text(
                "SELECT 1 FROM experiment_assignment WHERE user_id=:id AND experiment_id=:campaign"
            ),
            {"id": USER, "campaign": ex.CAMPAIGN},
        )
        is None
    )


@pytest.mark.asyncio
async def test_legacy_delivery_and_recent_activity_prevent_send(opportunity_user):
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE user_meme_reaction SET sent_at=timezone('UTC',now()), "
                "recommended_by='broadcast_reengagement_hq' WHERE user_id=:id"
            ),
            {"id": USER},
        )
    assert await ex.reserve_opportunity(USER, True) is None


@pytest.mark.asyncio
async def test_stale_sending_disables_later_enrollment(opportunity_user):
    row = await ex.reserve_opportunity(USER, True)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE push_content_opportunity SET state='sending', "
                "attempted_at=timezone('UTC',now())-interval '3 minutes' WHERE id=:id"
            ),
            {"id": row["id"]},
        )
    await ex.reserve_opportunity(USER, True)
    state = await fetch_one(
        text("SELECT * FROM push_content_control WHERE campaign=:campaign"),
        {"campaign": ex.CAMPAIGN},
    )
    assert not state["enabled"] and state["pause_reason"] == "stale_sending"


@pytest.mark.asyncio
async def test_zero_attempt_harm_and_accepted_state_survive_unknown(opportunity_user):
    row = await ex.reserve_opportunity(USER, True)
    await ex.check_harm()
    await ex._update(row["id"], "selected")
    await ex._update(row["id"], "sending")
    await ex._update(row["id"], "accepted", telegram_message_id=44)
    await ex._update(row["id"], "unknown", error_code="late_timeout")
    state = await fetch_one(
        text("SELECT state FROM push_content_opportunity WHERE id=:id"), {"id": row["id"]}
    )
    assert state["state"] == "accepted"


@pytest.mark.asyncio
async def test_dispatch_timeout_quarantines_and_prevents_retry(opportunity_user, monkeypatch):
    from src.recommendations import broadcast_pick

    picked = MemeData(id=CHOSEN, type="image", telegram_file_id="test", caption=None)
    monkeypatch.setattr(
        broadcast_pick,
        "pick_exploration_meme",
        AsyncMock(return_value=(picked, "broadcast_reengagement_hq", {})),
    )

    async def timeout(*args, **kwargs):
        await kwargs["on_sending"]()
        raise asyncio.TimeoutError

    send = AsyncMock(side_effect=timeout)
    monkeypatch.setattr(ex, "send_meme_to_user", send)
    await ex.dispatch_opportunity(USER)
    row = await fetch_one(
        text("SELECT state FROM push_content_opportunity WHERE user_id=:id"), {"id": USER}
    )
    assert row["state"] == "unknown"
    assert await ex.dispatch_opportunity(USER) == "duplicate_or_ineligible"
    assert send.await_count == 1


@pytest.mark.asyncio
async def test_accepted_local_failure_retains_receipt_and_pauses(opportunity_user, monkeypatch):
    from src.recommendations import broadcast_pick

    picked = MemeData(id=CHOSEN, type="image", telegram_file_id="test", caption=None)
    monkeypatch.setattr(
        broadcast_pick,
        "pick_exploration_meme",
        AsyncMock(return_value=(picked, "broadcast_reengagement_hq", {})),
    )

    async def local_failure(*args, **kwargs):
        await kwargs["on_sending"]()
        await kwargs["on_accepted"](SimpleNamespace(message_id=77))
        raise ValueError("reaction write failure")

    monkeypatch.setattr(ex, "send_meme_to_user", AsyncMock(side_effect=local_failure))
    assert await ex.dispatch_opportunity(USER) == "accepted"
    row = await fetch_one(
        text("SELECT * FROM push_content_opportunity WHERE user_id=:id"), {"id": USER}
    )
    assert row["state"] == "accepted" and row["telegram_message_id"] == 77
    assert row["error_code"] == "post_acceptance_bookkeeping"


@pytest.mark.asyncio
async def test_reactivated_user_is_skipped_before_network(opportunity_user, monkeypatch):
    from src.recommendations import broadcast_pick

    picked = MemeData(id=CHOSEN, type="image", telegram_file_id="test", caption=None)
    monkeypatch.setattr(
        broadcast_pick,
        "pick_exploration_meme",
        AsyncMock(return_value=(picked, "broadcast_reengagement_explore", {})),
    )
    network = AsyncMock()

    async def prepare_then_reactivate(*args, **kwargs):
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE \"user\" SET last_active_at=timezone('UTC',now()) WHERE id=:id"),
                {"id": USER},
            )
        await kwargs["on_sending"]()
        await network()

    monkeypatch.setattr(ex, "send_meme_to_user", prepare_then_reactivate)
    await ex.dispatch_opportunity(USER)
    network.assert_not_awaited()
    row = await fetch_one(
        text("SELECT state,attempted_at FROM push_content_opportunity WHERE user_id=:id"),
        {"id": USER},
    )
    assert row["state"] == "skipped" and row["attempted_at"] is None


@pytest.mark.asyncio
async def test_disabled_dispatch_uses_legacy_picker_once(opportunity_user, monkeypatch):
    from src.recommendations import broadcast_pick

    monkeypatch.setattr(ex.settings, "DORMANT_PUSH_EXPLORATION_ENABLED", False)
    legacy = AsyncMock(return_value=(None, "broadcast_reengagement"))
    exploration = AsyncMock()
    monkeypatch.setattr(broadcast_pick, "pick_reengagement_meme", legacy)
    monkeypatch.setattr(broadcast_pick, "pick_exploration_meme", exploration)
    await ex.dispatch_opportunity(USER)
    await ex.dispatch_opportunity(USER)
    legacy.assert_awaited_once_with(USER)
    exploration.assert_not_awaited()
