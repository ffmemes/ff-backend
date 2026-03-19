"""Integration tests for batch stats computation.

Covers user_stats and user_meme_source_stats (sole-writer batch functions).
"""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from tests.factories import (
    cleanup_test_data,
    create_meme,
    create_meme_source,
    create_reaction,
    create_user,
    create_user_language,
)

from src.database import engine, user_meme_source_stats, user_stats
from src.stats.user import calculate_user_stats
from src.stats.user_meme_source import calculate_user_meme_source_stats

USER_A = 10001
USER_B = 10002
SOURCE_1 = 10001
SOURCE_2 = 10002


@pytest_asyncio.fixture(loop_scope="session")
async def setup():
    """Create test users, sources, and memes."""
    async with engine.connect() as conn:
        await create_user(conn, id=USER_A)
        await create_user(conn, id=USER_B)
        await create_user_language(conn, user_id=USER_A)
        await create_user_language(conn, user_id=USER_B)
        await create_meme_source(conn, id=SOURCE_1)
        await create_meme_source(conn, id=SOURCE_2, url="https://t.me/test_s2")

        for i in range(1, 11):
            source = SOURCE_1 if i <= 6 else SOURCE_2
            await create_meme(conn, id=10000 + i, meme_source_id=source)

        await conn.commit()

    yield

    async with engine.connect() as conn:
        await cleanup_test_data(conn)


async def _get_user_stats(user_id: int) -> dict | None:
    async with engine.connect() as conn:
        row = await conn.execute(select(user_stats).where(user_stats.c.user_id == user_id))
        result = row.first()
        return result._asdict() if result else None


async def _get_user_source_stats(user_id: int, source_id: int) -> dict | None:
    async with engine.connect() as conn:
        row = await conn.execute(
            select(user_meme_source_stats).where(
                user_meme_source_stats.c.user_id == user_id,
                user_meme_source_stats.c.meme_source_id == source_id,
            )
        )
        result = row.first()
        return result._asdict() if result else None


async def _clear_stats():
    """Clear all test stats rows so we can compare fresh runs."""
    async with engine.connect() as conn:
        await conn.execute(delete(user_stats).where(user_stats.c.user_id >= 10000))
        await conn.execute(
            delete(user_meme_source_stats).where(user_meme_source_stats.c.user_id >= 10000)
        )
        await conn.commit()


@pytest.mark.asyncio
async def test_user_stats_correct_counts(setup):
    """Batch user_stats produces correct like/dislike/sent counts."""
    base_time = datetime.utcnow() - timedelta(hours=1)

    async with engine.connect() as conn:
        for i, (meme_id, reaction) in enumerate(
            [
                (10001, 1),
                (10002, 1),
                (10003, 1),  # 3 likes from source 1
                (10004, 2),
                (10005, 2),  # 2 dislikes from source 1
                (10007, 1),
                (10008, 1),  # 2 likes from source 2
                (10009, 2),  # 1 dislike from source 2
            ]
        ):
            t = base_time + timedelta(seconds=i * 10)
            await create_reaction(
                conn,
                USER_A,
                meme_id,
                reaction_id=reaction,
                sent_at=t,
                reacted_at=t + timedelta(seconds=3),
            )
        await conn.commit()

    await _clear_stats()
    await calculate_user_stats()

    stats = await _get_user_stats(USER_A)
    assert stats is not None
    assert stats["nlikes"] == 5
    assert stats["ndislikes"] == 3
    assert stats["nmemes_sent"] == 8
    assert stats["active_days_count"] >= 1
    assert stats["time_spent_sec"] >= 0


@pytest.mark.asyncio
async def test_user_stats_only_recent_users(setup):
    """HAVING filter: only users active in last 24h get rows."""
    old_time = datetime.utcnow() - timedelta(hours=48)

    async with engine.connect() as conn:
        # User B reacted 48 hours ago — should NOT appear in stats
        await create_reaction(
            conn,
            USER_B,
            10002,
            reaction_id=1,
            sent_at=old_time,
            reacted_at=old_time + timedelta(seconds=5),
        )
        await conn.commit()

    await _clear_stats()
    await calculate_user_stats()

    stats_b = await _get_user_stats(USER_B)
    assert stats_b is None  # User B should be filtered out by HAVING


@pytest.mark.asyncio
async def test_user_meme_source_stats_correct(setup):
    """Batch user_meme_source_stats produces correct per-source counts."""
    base_time = datetime.utcnow() - timedelta(hours=3)

    async with engine.connect() as conn:
        # User A: 3 likes + 2 dislikes from source 1, 2 likes + 1 dislike from source 2
        for i, (meme_id, reaction) in enumerate(
            [
                (10001, 1),
                (10002, 1),
                (10003, 1),  # 3 likes from source 1
                (10004, 2),
                (10005, 2),  # 2 dislikes from source 1
                (10007, 1),
                (10008, 1),  # 2 likes from source 2
                (10009, 2),  # 1 dislike from source 2
            ]
        ):
            t = base_time + timedelta(seconds=i * 10)
            await create_reaction(
                conn,
                USER_A,
                meme_id,
                reaction_id=reaction,
                sent_at=t,
                reacted_at=t + timedelta(seconds=3),
            )
        await conn.commit()

    await _clear_stats()
    await calculate_user_meme_source_stats()

    s1 = await _get_user_source_stats(USER_A, SOURCE_1)
    s2 = await _get_user_source_stats(USER_A, SOURCE_2)

    assert s1 is not None
    assert s1["nlikes"] == 3
    assert s1["ndislikes"] == 2

    assert s2 is not None
    assert s2["nlikes"] == 2
    assert s2["ndislikes"] == 1
