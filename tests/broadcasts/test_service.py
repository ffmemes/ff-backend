from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import delete
from tests.factories import (
    create_meme,
    create_meme_source,
    create_reaction,
    create_user,
    create_user_language,
)

from src.broadcasts.service import (
    drop_holdout,
    get_all_non_blocked_users,
    get_monthly_reminder_user_ids,
    get_user_ids_active_minutes_ago,
    get_users_inactive_since_days,
    get_users_with_language,
    holdout_variant,
    send_meme_broadcast,
)
from src.database import (
    engine,
    meme,
    meme_source,
    user,
    user_language,
    user_meme_reaction,
    user_stats,
    user_tg,
)
from src.storage.constants import MemeType
from src.storage.schemas import MemeData

ACTIVE_USER_ID = 311001
BLOCKED_ADMIN_ID = 311002
LEGACY_BLOCKED_USER_ID = 311003
WAITLIST_USER_ID = 311004
ACTIVE_ADMIN_ID = 311005
TEST_USER_IDS = (
    ACTIVE_USER_ID,
    BLOCKED_ADMIN_ID,
    LEGACY_BLOCKED_USER_ID,
    WAITLIST_USER_ID,
    ACTIVE_ADMIN_ID,
)


@pytest_asyncio.fixture()
async def cleanup_broadcast_users():
    await _cleanup()
    yield
    await _cleanup()


TEST_MEME_ID = 311101


async def _cleanup() -> None:
    async with engine.connect() as conn:
        await conn.execute(
            delete(user_meme_reaction).where(user_meme_reaction.c.user_id.in_(TEST_USER_IDS))
        )
        await conn.execute(delete(user_stats).where(user_stats.c.user_id.in_(TEST_USER_IDS)))
        await conn.execute(delete(meme).where(meme.c.id == TEST_MEME_ID))
        await conn.execute(delete(meme_source).where(meme_source.c.id == TEST_MEME_ID))
        await conn.execute(delete(user_language).where(user_language.c.user_id.in_(TEST_USER_IDS)))
        await conn.execute(delete(user_tg).where(user_tg.c.id.in_(TEST_USER_IDS)))
        await conn.execute(delete(user).where(user.c.id.in_(TEST_USER_IDS)))
        await conn.commit()


@pytest.mark.asyncio
async def test_get_users_with_language_skips_blocked_transport_state(
    cleanup_broadcast_users,
) -> None:
    async with engine.connect() as conn:
        await create_user(conn, id=ACTIVE_USER_ID)
        await create_user(conn, id=BLOCKED_ADMIN_ID, type="admin")
        await create_user(conn, id=LEGACY_BLOCKED_USER_ID, type="blocked_bot")
        await create_user(conn, id=WAITLIST_USER_ID, type="waitlist")
        await create_user(conn, id=ACTIVE_ADMIN_ID, type="admin")
        for user_id in TEST_USER_IDS:
            await create_user_language(conn, user_id=user_id, language_code="ru")
        await conn.execute(
            user.update()
            .where(user.c.id == BLOCKED_ADMIN_ID)
            .values(blocked_bot_at=datetime(2026, 5, 25, 12, 0, 0))
        )
        await conn.commit()

    rows = await get_users_with_language("ru")

    assert {row["user_id"] for row in rows if row["user_id"] in TEST_USER_IDS} == {
        ACTIVE_USER_ID,
        ACTIVE_ADMIN_ID,
    }


@pytest.mark.asyncio
async def test_get_all_non_blocked_users_skips_blocked_transport_state(
    cleanup_broadcast_users,
) -> None:
    async with engine.connect() as conn:
        await create_user(conn, id=ACTIVE_USER_ID)
        await create_user(conn, id=BLOCKED_ADMIN_ID, type="admin")
        await create_user(conn, id=LEGACY_BLOCKED_USER_ID, type="blocked_bot")
        await create_user(conn, id=ACTIVE_ADMIN_ID, type="admin")
        for user_id in (
            ACTIVE_USER_ID,
            BLOCKED_ADMIN_ID,
            LEGACY_BLOCKED_USER_ID,
            ACTIVE_ADMIN_ID,
        ):
            await create_user_language(conn, user_id=user_id, language_code="ru")
        await conn.execute(
            user.update()
            .where(user.c.id == BLOCKED_ADMIN_ID)
            .values(blocked_bot_at=datetime(2026, 5, 25, 12, 0, 0))
        )
        await conn.commit()

    rows = await get_all_non_blocked_users()

    assert {row["user_id"] for row in rows if row["user_id"] in TEST_USER_IDS} == {
        ACTIVE_USER_ID,
        ACTIVE_ADMIN_ID,
    }


@pytest.mark.asyncio
async def test_get_users_inactive_since_days_skips_recent_and_blocked(
    cleanup_broadcast_users,
) -> None:
    now = datetime.utcnow()
    idle_id = ACTIVE_USER_ID
    recent_id = ACTIVE_ADMIN_ID
    async with engine.connect() as conn:
        await create_user(conn, id=idle_id)
        await create_user(conn, id=recent_id)
        await create_user(conn, id=WAITLIST_USER_ID, type="waitlist")
        await create_user(conn, id=LEGACY_BLOCKED_USER_ID, type="blocked_bot")
        await conn.execute(
            user.update()
            .where(user.c.id == idle_id)
            .values(last_active_at=now - timedelta(days=10))
        )
        await conn.execute(
            user.update()
            .where(user.c.id == recent_id)
            .values(last_active_at=now - timedelta(days=2))
        )
        await conn.execute(
            user.update()
            .where(user.c.id == WAITLIST_USER_ID)
            .values(last_active_at=now - timedelta(days=20))
        )
        await conn.commit()

    rows = await get_users_inactive_since_days(7)
    ids = {user_id for user_id in rows if user_id in TEST_USER_IDS}
    assert idle_id in ids
    assert recent_id not in ids
    assert WAITLIST_USER_ID not in ids
    assert LEGACY_BLOCKED_USER_ID not in ids


@pytest.mark.asyncio
async def test_send_meme_broadcast_dry_run_does_not_send() -> None:
    pick = AsyncMock()
    send = AsyncMock()
    with (
        patch("src.broadcasts.service.redis_client.scard", AsyncMock(return_value=0)),
        patch("src.recommendations.broadcast_pick.pick_reengagement_meme", pick),
        patch("src.tgbot.senders.meme.send_meme_to_user", send),
    ):
        result = await send_meme_broadcast("test-dry", [1, 2], dry_run=True)

    pick.assert_not_called()
    send.assert_not_called()
    assert result["audience"] == 2
    assert result["sent"] == 0


@pytest.mark.asyncio
async def test_send_meme_broadcast_picks_per_user_and_dedups() -> None:
    meme = MemeData(
        id=11,
        type=MemeType.IMAGE,
        telegram_file_id="f",
        caption=None,
        recommended_by="broadcast_channel_viral",
    )
    pick = AsyncMock(return_value=(meme, "broadcast_channel_viral"))
    send = AsyncMock()
    seen: set[str] = set()

    async def sismember(_key, value):
        return value in seen

    async def sadd(_key, value):
        seen.add(value)
        return 1

    with (
        patch("src.broadcasts.service.redis_client.scard", AsyncMock(return_value=0)),
        patch("src.broadcasts.service.redis_client.sismember", sismember),
        patch("src.broadcasts.service.redis_client.sadd", sadd),
        patch("src.broadcasts.service.bot", object()),
        patch("src.recommendations.broadcast_pick.pick_reengagement_meme", pick),
        patch("src.tgbot.senders.meme.send_meme_to_user", send),
    ):
        result = await send_meme_broadcast("test-real", [7, 8], delay=0)
        result_again = await send_meme_broadcast("test-real", [7, 8], delay=0)

    assert pick.await_count == 2
    assert send.await_count == 2
    assert result["sent"] == 2
    assert send.await_args.kwargs["recommended_by"] == "broadcast_channel_viral"
    assert result_again["skipped"] == 2
    assert result_again["sent"] == 0


@pytest.mark.asyncio
async def test_cadence_targeting_requires_recent_reaction(cleanup_broadcast_users) -> None:
    now = datetime.utcnow()
    reacted_id, stale_id = ACTIVE_USER_ID, ACTIVE_ADMIN_ID
    async with engine.connect() as conn:
        await create_meme_source(conn, id=TEST_MEME_ID)
        await create_meme(conn, id=TEST_MEME_ID, meme_source_id=TEST_MEME_ID)
        for user_id, reacted_at in ((reacted_id, now), (stale_id, now - timedelta(days=40))):
            await create_user(conn, id=user_id)
            await conn.execute(
                user.update()
                .where(user.c.id == user_id)
                .values(last_active_at=now - timedelta(minutes=20))
            )
            await create_reaction(
                conn, user_id=user_id, meme_id=TEST_MEME_ID, reaction_id=1, reacted_at=reacted_at
            )
        await conn.commit()

    ids = set(await get_user_ids_active_minutes_ago(15, 30)) & set(TEST_USER_IDS)
    assert ids == {reacted_id}


@pytest.mark.asyncio
async def test_monthly_reminder_selects_29_to_365_day_reactors(cleanup_broadcast_users) -> None:
    now = datetime.utcnow()
    cases = {
        ACTIVE_USER_ID: now - timedelta(days=60),  # in
        ACTIVE_ADMIN_ID: now - timedelta(days=10),  # too recent
        WAITLIST_USER_ID: now - timedelta(days=400),  # too old
        BLOCKED_ADMIN_ID: now - timedelta(days=60),  # blocked
    }
    async with engine.connect() as conn:
        for user_id, last_reaction_at in cases.items():
            await create_user(conn, id=user_id)
            await conn.execute(
                user_stats.insert().values(user_id=user_id, last_reaction_at=last_reaction_at)
            )
        await create_user(conn, id=LEGACY_BLOCKED_USER_ID)  # never reacted: no user_stats
        await conn.execute(
            user.update().where(user.c.id == BLOCKED_ADMIN_ID).values(blocked_bot_at=now)
        )
        await conn.commit()

    ids = set(await get_monthly_reminder_user_ids()) & set(TEST_USER_IDS)
    assert ids == {ACTIVE_USER_ID}


@pytest.mark.asyncio
async def test_drop_holdout_is_deterministic_and_logged() -> None:
    share = sum(holdout_variant("exp", uid, 15) == "holdout" for uid in range(10_000)) / 10_000
    assert 0.13 < share < 0.17
    assert all(holdout_variant("exp", uid, 0) == "treatment" for uid in range(1000))

    user_ids = list(range(100))
    assign = AsyncMock()
    with patch("src.broadcasts.service.assign_experiment", assign):
        treated = await drop_holdout("exp", user_ids, 20)

    assert treated == [u for u in user_ids if holdout_variant("exp", u, 20) == "treatment"]
    assert 0 < len(treated) < 100
    assert assign.await_count == 100
    assert {c.args[2] for c in assign.await_args_list} == {"treatment", "holdout"}
