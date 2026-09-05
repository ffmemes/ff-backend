import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import text
from tests.factories import (
    cleanup_test_data,
    create_meme,
    create_meme_source,
    create_user,
    create_user_language,
)

from src import redis
from src.database import engine
from src.recommendations import channel_hits as hits
from src.tgbot.repo.memes import get_shareable_meme_by_id

USER = 33001
MEME = 33001
SOURCE = 33001


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def test_pool_uses_exposure_and_channel_baseline_not_raw_forward_count():
    labels = [
        {"id": i, "channel": channel, "posted_at": _now(), "views": views, "forwards": i}
        for channel, views in [("tgchannelru", 400), ("tgchannelen", 80)]
        for i in range(20)
    ]
    labels.extend(
        [
            {
                "id": 100,
                "channel": "tgchannelru",
                "posted_at": _now(),
                "views": 10000,
                "forwards": 40,
            },
            {"id": 101, "channel": "tgchannelru", "posted_at": _now(), "views": 5, "forwards": 4},
        ]
    )
    pool = hits.score_channel_hits(labels)
    assert {100, 101}.isdisjoint(row["id"] for row in pool)
    assert {row["channel"] for row in pool} == {"tgchannelru", "tgchannelen"}
    assert all(row["raw_rate"] >= row["raw_p75"] for row in pool)
    assert all(0 <= row["percentile"] <= 1 for row in pool)
    assert all(row["prior_rate"] < row["smoothed_rate"] < row["raw_rate"] for row in pool)


def test_pool_requires_reference_supply_and_positive_shares():
    assert hits.score_channel_hits([]) == []
    labels = [
        {"id": i, "channel": "tgchannelen", "posted_at": _now(), "views": 75, "forwards": 0}
        for i in range(20)
    ]
    assert hits.score_channel_hits(labels) == []


@pytest_asyncio.fixture
async def channel_data(monkeypatch):
    monkeypatch.setattr(hits.settings, "CHANNEL_HITS_ENABLED", True)
    async with engine.begin() as conn:
        await create_user(conn, USER)
        await create_user_language(conn, USER)
        await create_meme_source(conn, SOURCE)
        for mid in range(MEME, MEME + 40):
            await create_meme(conn, mid, SOURCE, status="published", telegram_file_id=str(mid))
        await conn.execute(
            text("""
            INSERT INTO crossposting(channel, meme_id, created_at, telegram_message_id)
            VALUES ('tgchannelru', :id, NOW() - interval '3 days', 1)
        """),
            {"id": MEME},
        )
        for chat_id in hits.CHANNEL_CHAT_IDS.values():
            await conn.execute(
                text("""
                INSERT INTO user_channel_membership(user_id, chat_id, status, observed_at)
                VALUES (:user_id, :chat_id, 'nonmember', NOW())
            """),
                {"user_id": USER, "chat_id": chat_id},
            )
        await conn.execute(
            text("""
            INSERT INTO experiment_assignment(experiment_id, user_id, variant, assignment_metadata)
            VALUES (:experiment_id, :user_id, 'treatment', CAST(:metadata AS jsonb))
        """),
            {
                "experiment_id": hits.EXPERIMENT_ID,
                "user_id": USER,
                "metadata": json.dumps(
                    {
                        "experiment_start_at": (_now() - timedelta(hours=1)).isoformat() + "Z",
                        "exposure_end_at": (_now() + timedelta(days=14)).isoformat() + "Z",
                    }
                ),
            },
        )
    await redis.redis_client.set(
        hits.POOL_KEY,
        json.dumps([{"id": MEME, "percentile": 0.99, "posted_at": _now().isoformat()}]),
    )
    await redis.redis_client.set(hits.COHORT_KEY, json.dumps([USER]))
    attempts_key = hits._attempts_key(USER)
    await redis.redis_client.delete(attempts_key)
    yield
    await redis.redis_client.delete(hits.POOL_KEY, hits.COHORT_KEY, attempts_key)
    async with engine.connect() as conn:
        await cleanup_test_data(conn)


@pytest.mark.asyncio
async def test_confirmed_nonmember_gets_only_one_session_attempt_without_touching_queue(
    channel_data,
):
    first = await hits.maybe_get_channel_hit(USER)
    assert first.id == MEME and first.recommended_by == hits.RECOMMENDED_BY
    assert await hits.maybe_get_channel_hit(USER) is None


@pytest.mark.asyncio
async def test_nonparticipants_skip_database_queries(channel_data, monkeypatch):
    query = AsyncMock(side_effect=AssertionError("Nonparticipants must not query PostgreSQL"))
    monkeypatch.setattr(hits, "fetch_one", query)
    assert await hits.maybe_get_channel_hit(USER + 99) is None
    query.assert_not_awaited()


@pytest.mark.asyncio
async def test_pool_refresh_queries_mature_equal_age_snapshots(channel_data):
    posted = _now() - timedelta(days=3)
    async with engine.begin() as conn:
        for offset in range(20):
            mid = MEME + 20 + offset
            await create_meme(conn, mid, SOURCE, status="published", telegram_file_id=str(mid))
            await conn.execute(
                text("""
                INSERT INTO crossposting(channel,meme_id,created_at,telegram_message_id)
                VALUES ('tgchannelru',:id,:posted,:message_id)
            """),
                {"id": mid, "posted": posted, "message_id": mid},
            )
            for age, forwards in [(24, offset), (48, 1000)]:
                await conn.execute(
                    text("""
                    INSERT INTO crossposting_snapshots
                        (channel,meme_id,telegram_message_id,views,forwards,snapshot_at)
                    VALUES ('tgchannelru',:id,:message_id,400,:forwards,:snapshot_at)
                """),
                    {
                        "id": mid,
                        "message_id": mid,
                        "forwards": forwards,
                        "snapshot_at": posted + timedelta(hours=age),
                    },
                )
    pool = await hits.refresh_channel_hit_pool()
    assert len(pool) == 5
    assert {row["forwards"] for row in pool} == {15, 16, 17, 18, 19}


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["member", "unknown", "missing", "former", "stale"])
async def test_subscription_uncertainty_and_past_membership_exclude(channel_data, state):
    async with engine.begin() as conn:
        if state == "missing":
            await conn.execute(
                text("DELETE FROM user_channel_membership WHERE user_id=:id"), {"id": USER}
            )
        elif state in {"member", "unknown"}:
            await conn.execute(
                text("""
                UPDATE user_channel_membership SET status=:state WHERE user_id=:id
            """),
                {"id": USER, "state": state},
            )
        else:
            await conn.execute(
                text("""
                UPDATE user_channel_membership
                SET ever_member=:former,
                    observed_at=NOW() - CAST(:age AS interval) WHERE user_id=:id
            """),
                {
                    "id": USER,
                    "former": state == "former",
                    "age": timedelta(hours=25) if state == "stale" else timedelta(minutes=1),
                },
            )
    assert await hits.eligible_channel_hits(USER) == []


@pytest.mark.asyncio
async def test_checks_every_publishing_channel_even_nonwinning_alias(channel_data):
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE meme SET status='duplicate', duplicate_of=:root WHERE id=:id"),
            {"root": MEME, "id": MEME + 1},
        )
        await conn.execute(
            text("""
            INSERT INTO crossposting(channel,meme_id) VALUES ('tgchannelen',:id)
        """),
            {"id": MEME + 1},
        )
        await conn.execute(
            text("""
            UPDATE user_channel_membership SET status='member'
            WHERE user_id=:id AND chat_id=:chat_id
        """),
            {"id": USER, "chat_id": hits.CHANNEL_CHAT_IDS["tgchannelen"]},
        )
    assert await hits.eligible_channel_hits(USER) == []


@pytest.mark.asyncio
async def test_alias_delivery_without_reaction_still_blocks(channel_data):
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE meme SET status='duplicate', duplicate_of=:root WHERE id=:id"),
            {"root": MEME, "id": MEME + 1},
        )
        await conn.execute(
            text("""
            INSERT INTO user_meme_reaction(user_id,meme_id,recommended_by)
            VALUES (:user_id,:id,'test')
        """),
            {"user_id": USER, "id": MEME + 1},
        )
    assert await hits.eligible_channel_hits(USER) == []


@pytest.mark.asyncio
async def test_membership_change_after_selection_cancels_delivery(channel_data):
    selected = await hits.maybe_get_channel_hit(USER)
    assert selected is not None
    async with engine.begin() as conn:
        await conn.execute(
            text("""
            UPDATE user_channel_membership SET status='member' WHERE user_id=:id
        """),
            {"id": USER},
        )
    assert not await hits.channel_hit_is_sendable(USER, selected.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("guard", ["control", "expired", "five_sent", "sent_hit", "legacy_hit"])
async def test_assignment_and_session_guards(channel_data, guard):
    async with engine.begin() as conn:
        if guard == "control":
            await conn.execute(
                text("UPDATE experiment_assignment SET variant='control' WHERE user_id=:id"),
                {"id": USER},
            )
        elif guard == "expired":
            await conn.execute(
                text("""
                UPDATE experiment_assignment SET assignment_metadata=jsonb_set(
                    assignment_metadata,'{exposure_end_at}',to_jsonb('2020-01-01T00:00:00Z'::text))
                WHERE user_id=:id
            """),
                {"id": USER},
            )
        else:
            count = 5 if guard == "five_sent" else 1
            sent_at = _now() - timedelta(seconds=1)
            for offset in range(count):
                await conn.execute(
                    text("""
                    INSERT INTO user_meme_reaction(user_id,meme_id,sent_at,recommended_by)
                    VALUES (:user_id,:meme_id,:sent_at,:recommended_by)
                """),
                    {
                        "user_id": USER,
                        "meme_id": MEME + 1 + offset,
                        "sent_at": sent_at,
                        "recommended_by": {
                            "sent_hit": hits.RECOMMENDED_BY,
                            "legacy_hit": "channel_hit_v1",
                        }.get(guard, "test"),
                    },
                )
    assert await hits.maybe_get_channel_hit(USER) is None


@pytest.mark.asyncio
async def test_explicit_published_share_resolves_alias_without_subscription_gate(channel_data):
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE meme SET status='duplicate', duplicate_of=:root WHERE id=:id"),
            {"root": MEME, "id": MEME + 1},
        )
        await conn.execute(
            text("UPDATE user_channel_membership SET status='member' WHERE user_id=:id"),
            {"id": USER},
        )
    assert (await get_shareable_meme_by_id(MEME))["id"] == MEME
    assert (await get_shareable_meme_by_id(MEME + 1))["id"] == MEME
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE meme SET status='rejected' WHERE id=:id"), {"id": MEME})
    assert await get_shareable_meme_by_id(MEME + 1) is None


async def _record_sends(rows):
    async with engine.begin() as conn:
        for offset, sent_at, label in rows:
            await conn.execute(
                text("""
                    INSERT INTO user_meme_reaction(user_id,meme_id,sent_at,recommended_by)
                    VALUES (:user_id,:meme_id,:sent_at,:recommended_by)
                """),
                {
                    "user_id": USER,
                    "meme_id": MEME + offset,
                    "sent_at": sent_at,
                    "recommended_by": label,
                },
            )


def _freeze_now(monkeypatch, moment):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            aware = moment.replace(tzinfo=timezone.utc)
            return aware.astimezone(tz) if tz else moment

    monkeypatch.setattr(hits, "datetime", FrozenDatetime)


@pytest.mark.asyncio
@pytest.mark.parametrize("current_sends", [0, 4, 5])
async def test_return_visit_gets_first_five_window(channel_data, monkeypatch, current_sends):
    now = _now()
    _freeze_now(monkeypatch, now)
    # The first visit already exhausted its window, with no reactions required.
    rows = [(i + 1, now - timedelta(hours=2, minutes=i), "test") for i in range(6)]
    rows += [(i + 10, now - timedelta(minutes=i + 1), "test") for i in range(current_sends)]
    await _record_sends(rows)
    assert (await hits.maybe_get_channel_hit(USER) is not None) == (current_sends < 5)


@pytest.mark.asyncio
@pytest.mark.parametrize("gap_seconds", [1800, 1801])
async def test_session_gap_is_strictly_over_thirty_minutes(channel_data, monkeypatch, gap_seconds):
    now = _now()
    _freeze_now(monkeypatch, now)
    await _record_sends(
        [(i + 1, now - timedelta(seconds=gap_seconds + i), "test") for i in range(5)]
    )
    assert (await hits.maybe_get_channel_hit(USER) is not None) == (gap_seconds > 1800)


@pytest.mark.asyncio
async def test_midnight_does_not_reset_continuous_session(channel_data, monkeypatch):
    now = (_now() + timedelta(days=1)).replace(hour=0, minute=2, second=0, microsecond=0)
    _freeze_now(monkeypatch, now)
    await _record_sends([(i + 1, now - timedelta(minutes=i + 1), "test") for i in range(6)])
    assert await hits.maybe_get_channel_hit(USER) is None


@pytest.mark.asyncio
async def test_passive_and_explicit_content_does_not_create_or_extend_session(channel_data):
    labels = [
        "broadcast",
        "broadcast_reengagement",
        "uploaded_meme",
        "low_sent_pool",
        "friend_challenge",
        "friend_challenge_reveal",
        "share_link",
        "last",
    ]
    now = _now()
    await _record_sends(
        [(i + 1, now - timedelta(seconds=1), label) for i, label in enumerate(labels)]
    )
    assert await hits.maybe_get_channel_hit(USER) is not None


@pytest.mark.asyncio
async def test_concurrent_requests_reserve_one_attempt(channel_data):
    attempts = await asyncio.gather(*(hits.maybe_get_channel_hit(USER) for _ in range(12)))
    assert sum(result is not None for result in attempts) == 1
    assert await redis.redis_client.zcard(hits._attempts_key(USER)) == 1


@pytest.mark.asyncio
async def test_reservation_survives_first_durable_send_without_duplicate_attempt(channel_data):
    assert await hits.maybe_get_channel_hit(USER) is not None
    # Simulate a failed/ambiguous hit followed by an ordinary durable delivery.
    await _record_sends([(1, _now(), "test")])
    assert await hits.maybe_get_channel_hit(USER) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "oldest_age", [timedelta(hours=23, minutes=59), timedelta(hours=24, seconds=1)]
)
async def test_rolling_quota_restores_from_durable_hits_after_redis_loss(
    channel_data, monkeypatch, oldest_age
):
    now = _now()
    _freeze_now(monkeypatch, now)
    await _record_sends(
        [
            (1, now - oldest_age, "channel_hit_v1"),
            (2, now - timedelta(hours=4), hits.RECOMMENDED_BY),
            (3, now - timedelta(hours=2), hits.RECOMMENDED_BY),
        ]
    )
    await redis.redis_client.delete(hits._attempts_key(USER))
    selected = await hits.maybe_get_channel_hit(USER)
    assert (selected is not None) == (oldest_age > timedelta(hours=24))
    if selected:
        assert await redis.redis_client.zcard(hits._attempts_key(USER)) == 3


@pytest.mark.asyncio
async def test_attempt_and_its_delivery_count_once_in_rolling_quota(channel_data, monkeypatch):
    now = _now()
    for offset in range(4):
        moment = now + timedelta(hours=offset)
        _freeze_now(monkeypatch, moment)
        async with engine.begin() as conn:
            if offset:
                await conn.execute(
                    text("INSERT INTO crossposting(channel,meme_id) VALUES ('tgchannelru',:id)"),
                    {"id": MEME + offset},
                )
        await redis.redis_client.set(
            hits.POOL_KEY,
            json.dumps(
                [{"id": MEME + offset, "percentile": 0.99, "posted_at": moment.isoformat()}]
            ),
        )
        selected = await hits.maybe_get_channel_hit(USER)
        if offset == 3:
            assert selected is None
        else:
            assert selected is not None
            await _record_sends([(offset, moment, hits.RECOMMENDED_BY)])
            assert await redis.redis_client.zcard(hits._attempts_key(USER)) == offset + 1


@pytest.mark.asyncio
async def test_no_candidate_does_not_consume_attempt(channel_data):
    assert await hits.maybe_get_channel_hit(USER, exclude_meme_ids=[MEME]) is None
    assert not await redis.redis_client.exists(hits._attempts_key(USER))
    assert await hits.maybe_get_channel_hit(USER) is not None


@pytest.mark.asyncio
async def test_reservation_failure_falls_back_closed(channel_data, monkeypatch):
    monkeypatch.setattr(redis.redis_client, "eval", AsyncMock(side_effect=ConnectionError()))
    assert await hits.maybe_get_channel_hit(USER) is None


@pytest.mark.asyncio
async def test_ambiguous_attempts_allow_fresh_meme_next_visit_and_stop_at_three(
    channel_data, monkeypatch
):
    now = _now()
    async with engine.begin() as conn:
        for offset in range(1, 4):
            await conn.execute(
                text("INSERT INTO crossposting(channel,meme_id) VALUES ('tgchannelru',:id)"),
                {"id": MEME + offset},
            )
    await redis.redis_client.set(
        hits.POOL_KEY,
        json.dumps(
            [
                {"id": MEME + offset, "percentile": 1 - offset / 10, "posted_at": now.isoformat()}
                for offset in range(4)
            ]
        ),
    )
    for offset in range(4):
        _freeze_now(monkeypatch, now + timedelta(minutes=31 * offset))
        selected = await hits.maybe_get_channel_hit(USER)
        if offset < 3:
            assert selected is not None and selected.id == MEME + offset
        else:
            assert selected is None
    # The quota expires relative to actual attempts, not at midnight.
    _freeze_now(monkeypatch, now + timedelta(hours=24, seconds=1))
    assert await hits.maybe_get_channel_hit(USER) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("label", hits.HIT_RECOMMENDERS)
async def test_sender_rechecks_membership_for_both_hit_versions(channel_data, monkeypatch, label):
    from importlib import import_module
    from types import SimpleNamespace

    sender = import_module("src.tgbot.senders.next_message")
    selected = (await hits.eligible_channel_hits(USER))[0]
    selected["recommended_by"] = label
    selected = hits.MemeData(**selected)
    monkeypatch.setattr(sender, "get_user_info", AsyncMock(return_value={"nmemes_sent": 10}))
    monkeypatch.setattr(sender, "get_popup_to_send", AsyncMock(return_value=None))
    monkeypatch.setattr(sender, "maybe_get_channel_hit", AsyncMock(return_value=selected))
    monkeypatch.setattr(
        sender,
        "prepare_meme_delivery",
        AsyncMock(return_value=SimpleNamespace(caption="", reply_markup=None)),
    )
    recheck = AsyncMock(return_value=False)
    send = AsyncMock()
    monkeypatch.setattr(sender, "channel_hit_is_sendable", recheck)
    monkeypatch.setattr(sender, "send_new_message_with_meme", send)
    monkeypatch.setattr(sender, "send_queue_preparing_alert", AsyncMock())
    monkeypatch.setattr(sender.meme_queue, "check_queue", AsyncMock())
    await sender.next_message(object(), USER, SimpleNamespace(callback_query=None))
    assert recheck.await_count == 5
    send.assert_not_awaited()
