"""Tests for session gap (30 min) and median_session_length in user_stats."""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from tests.factories import (
    cleanup_test_data,
    create_meme,
    create_meme_source,
    create_reaction,
    create_user,
)

from src.database import engine, fetch_all, user_stats
from src.stats.user import calculate_user_stats

# Must be recent (within 1 day of NOW()) for the HAVING clause in user_stats
T0 = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)


@pytest_asyncio.fixture(loop_scope="session")
async def setup():
    async with engine.connect() as conn:
        await create_user(conn, id=10001)
        await create_meme_source(conn, id=10001)
        for mid in range(10001, 10021):
            await create_meme(conn, id=mid, meme_source_id=10001)
        await conn.commit()
    yield
    async with engine.connect() as conn:
        await cleanup_test_data(conn)


@pytest_asyncio.fixture()
async def clean_reactions(setup):
    """Clean reactions and user_stats between tests."""
    yield
    async with engine.connect() as conn:
        from sqlalchemy import delete

        from src.database import user_meme_reaction

        await conn.execute(delete(user_stats).where(user_stats.c.user_id >= 10000))
        await conn.execute(delete(user_meme_reaction).where(user_meme_reaction.c.user_id >= 10000))
        await conn.commit()


@pytest.mark.asyncio
async def test_session_gap_30min(setup, clean_reactions):
    """Reactions >30 min apart should be counted as separate sessions."""
    async with engine.connect() as conn:
        # Session 1: 5 memes, 1 min apart
        for i in range(5):
            await create_reaction(
                conn,
                user_id=10001,
                meme_id=10001 + i,
                reaction_id=1,
                sent_at=T0 + timedelta(minutes=i),
                reacted_at=T0 + timedelta(minutes=i, seconds=5),
            )

        # 45-minute gap → new session
        session2_start = T0 + timedelta(minutes=50)

        # Session 2: 3 memes, 1 min apart
        for i in range(3):
            await create_reaction(
                conn,
                user_id=10001,
                meme_id=10006 + i,
                reaction_id=1,
                sent_at=session2_start + timedelta(minutes=i),
                reacted_at=session2_start + timedelta(minutes=i, seconds=5),
            )
        await conn.commit()

    await calculate_user_stats()

    rows = await fetch_all(select(user_stats).where(user_stats.c.user_id == 10001))
    assert len(rows) == 1
    row = rows[0]

    # Should be 2 sessions (45 min gap > 30 min threshold)
    assert row["nsessions"] == 2


@pytest.mark.asyncio
async def test_median_session_length(setup, clean_reactions):
    """median_session_length should reflect the median of session sizes (sessions >= 2 memes)."""
    async with engine.connect() as conn:
        # Session 1: 10 memes
        for i in range(10):
            await create_reaction(
                conn,
                user_id=10001,
                meme_id=10001 + i,
                reaction_id=1,
                sent_at=T0 + timedelta(minutes=i),
                reacted_at=T0 + timedelta(minutes=i, seconds=5),
            )

        # 45-minute gap → session 2
        session2_start = T0 + timedelta(minutes=50)

        # Session 2: 4 memes
        for i in range(4):
            await create_reaction(
                conn,
                user_id=10001,
                meme_id=10011 + i,
                reaction_id=1,
                sent_at=session2_start + timedelta(minutes=i),
                reacted_at=session2_start + timedelta(minutes=i, seconds=5),
            )
        await conn.commit()

    await calculate_user_stats()

    rows = await fetch_all(select(user_stats).where(user_stats.c.user_id == 10001))
    assert len(rows) == 1
    row = rows[0]

    # Two sessions: 10 memes and 4 memes. Median = (10 + 4) / 2 = 7
    assert row["median_session_length"] == 7
