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
        for mid in range(MEME, MEME + 8):
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
    day_key = f"channel_hits:v1:day:{_now().date()}:{USER}"
    await redis.redis_client.delete(day_key)
    yield
    await redis.redis_client.delete(hits.POOL_KEY, hits.COHORT_KEY, day_key)
    async with engine.connect() as conn:
        await cleanup_test_data(conn)


@pytest.mark.asyncio
async def test_confirmed_nonmember_gets_only_one_daily_hit_without_touching_queue(channel_data):
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
@pytest.mark.parametrize("guard", ["control", "expired", "five_sent", "later_session", "sent_hit"])
async def test_assignment_and_daily_session_guards(channel_data, guard):
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
            sent_at = _now() - timedelta(minutes=35 if guard == "later_session" else 0)
            # Ensure the historical session remains in this UTC day in boundary runs.
            if sent_at.date() != _now().date():
                pytest.skip("First 35 minutes of UTC day have no previous session today")
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
                        "recommended_by": hits.RECOMMENDED_BY if guard == "sent_hit" else "test",
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
