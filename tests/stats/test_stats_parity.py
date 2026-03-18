"""Regression test: per-user stats (Tier 1) must produce identical results to batch stats (Tier 2).

This test verifies that update_single_user_stats and update_single_user_meme_source_stats
produce the same results as the batch calculate_* functions for the same user data.
"""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from tests.factories import (
    cleanup_test_data,
    create_meme,
    create_meme_source,
    create_reaction,
    create_user,
    create_user_language,
)

from src.database import engine, user_meme_source_stats, user_stats
from src.stats.user import calculate_user_stats, update_single_user_stats
from src.stats.user_meme_source import (
    calculate_user_meme_source_stats,
    update_single_user_meme_source_stats,
)

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
        row = await conn.execute(
            select(user_stats).where(user_stats.c.user_id == user_id)
        )
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
    from sqlalchemy import delete

    async with engine.connect() as conn:
        await conn.execute(delete(user_stats).where(user_stats.c.user_id >= 10000))
        await conn.execute(
            delete(user_meme_source_stats).where(
                user_meme_source_stats.c.user_id >= 10000
            )
        )
        await conn.commit()


@pytest.mark.asyncio
async def test_single_user_stats_matches_batch(setup):
    """Tier 1 per-user stats must match Tier 2 batch stats for the same data."""
    base_time = datetime.utcnow() - timedelta(hours=1)

    async with engine.connect() as conn:
        # User A: 5 likes, 3 dislikes across source 1 and source 2
        for i, (meme_id, reaction) in enumerate([
            (10001, 1), (10002, 1), (10003, 1),  # 3 likes from source 1
            (10004, 2), (10005, 2),                # 2 dislikes from source 1
            (10007, 1), (10008, 1),                # 2 likes from source 2
            (10009, 2),                            # 1 dislike from source 2
        ]):
            t = base_time + timedelta(seconds=i * 10)
            await create_reaction(
                conn, USER_A, meme_id,
                reaction_id=reaction, sent_at=t, reacted_at=t + timedelta(seconds=3),
            )
        await conn.commit()

    # --- Run Tier 2 batch ---
    await calculate_user_stats()
    await calculate_user_meme_source_stats()
    batch_us = await _get_user_stats(USER_A)
    batch_umss_s1 = await _get_user_source_stats(USER_A, SOURCE_1)
    batch_umss_s2 = await _get_user_source_stats(USER_A, SOURCE_2)

    # --- Clear and run Tier 1 per-user ---
    await _clear_stats()
    await update_single_user_stats(USER_A)
    await update_single_user_meme_source_stats(USER_A)
    tier1_us = await _get_user_stats(USER_A)
    tier1_umss_s1 = await _get_user_source_stats(USER_A, SOURCE_1)
    tier1_umss_s2 = await _get_user_source_stats(USER_A, SOURCE_2)

    # --- Assert parity ---
    assert batch_us is not None and tier1_us is not None

    # Core metrics must match exactly
    assert tier1_us["nlikes"] == batch_us["nlikes"] == 5
    assert tier1_us["ndislikes"] == batch_us["ndislikes"] == 3
    assert tier1_us["nmemes_sent"] == batch_us["nmemes_sent"] == 8
    assert tier1_us["nsessions"] == batch_us["nsessions"]
    assert tier1_us["active_days_count"] == batch_us["active_days_count"]
    assert tier1_us["time_spent_sec"] == batch_us["time_spent_sec"]
    assert tier1_us["median_session_length"] == batch_us["median_session_length"]

    # Source stats must match
    assert batch_umss_s1 is not None and tier1_umss_s1 is not None
    assert tier1_umss_s1["nlikes"] == batch_umss_s1["nlikes"] == 3
    assert tier1_umss_s1["ndislikes"] == batch_umss_s1["ndislikes"] == 2

    assert batch_umss_s2 is not None and tier1_umss_s2 is not None
    assert tier1_umss_s2["nlikes"] == batch_umss_s2["nlikes"] == 2
    assert tier1_umss_s2["ndislikes"] == batch_umss_s2["ndislikes"] == 1


@pytest.mark.asyncio
async def test_single_user_does_not_affect_other_users(setup):
    """Tier 1 update for user A must not create/modify stats for user B."""
    base_time = datetime.utcnow() - timedelta(hours=2)

    async with engine.connect() as conn:
        await create_reaction(
            conn, USER_A, 10001,
            reaction_id=1, sent_at=base_time, reacted_at=base_time + timedelta(seconds=5),
        )
        await create_reaction(
            conn, USER_B, 10002,
            reaction_id=2, sent_at=base_time, reacted_at=base_time + timedelta(seconds=5),
        )
        await conn.commit()

    await _clear_stats()
    await update_single_user_stats(USER_A)
    await update_single_user_meme_source_stats(USER_A)

    us_a = await _get_user_stats(USER_A)
    us_b = await _get_user_stats(USER_B)
    umss_b = await _get_user_source_stats(USER_B, SOURCE_1)

    assert us_a is not None
    assert us_b is None  # Must not exist — we only updated user A
    assert umss_b is None
