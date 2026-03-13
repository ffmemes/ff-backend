"""Tests for calculate_user_meme_source_stats()."""

from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from tests.factories import (
    FIXED_DT,
    cleanup_test_data,
    create_meme,
    create_meme_source,
    create_reaction,
    create_user,
    create_user_language,
)

from src.database import engine, user_meme_source_stats
from src.stats.user_meme_source import calculate_user_meme_source_stats


@pytest_asyncio.fixture(loop_scope="session")
async def setup():
    async with engine.connect() as conn:
        await create_user(conn, id=10001)
        await create_user(conn, id=10002)
        await create_user_language(conn, user_id=10001)
        await create_user_language(conn, user_id=10002)

        await create_meme_source(conn, id=10001)
        await create_meme_source(conn, id=10002, url="https://t.me/test_source_10002")

        # Memes from source 10001
        await create_meme(conn, id=10001, meme_source_id=10001)
        await create_meme(conn, id=10002, meme_source_id=10001)
        await create_meme(conn, id=10003, meme_source_id=10001)
        await create_meme(conn, id=10004, meme_source_id=10001)

        # Memes from source 10002
        await create_meme(conn, id=10005, meme_source_id=10002)
        await create_meme(conn, id=10006, meme_source_id=10002)

        await conn.commit()

    yield

    async with engine.connect() as conn:
        await cleanup_test_data(conn)


async def _get_umss(user_id: int, meme_source_id: int) -> dict | None:
    async with engine.connect() as conn:
        row = await conn.execute(
            select(user_meme_source_stats).where(
                user_meme_source_stats.c.user_id == user_id,
                user_meme_source_stats.c.meme_source_id == meme_source_id,
            )
        )
        result = row.first()
        return result._asdict() if result else None


@pytest.mark.asyncio
async def test_calculates_nlikes_ndislikes(setup):
    async with engine.connect() as conn:
        await create_reaction(conn, 10001, 10001, reaction_id=1, reacted_at=FIXED_DT)
        await create_reaction(conn, 10001, 10002, reaction_id=1, reacted_at=FIXED_DT)
        await create_reaction(conn, 10001, 10003, reaction_id=1, reacted_at=FIXED_DT)
        await create_reaction(conn, 10001, 10004, reaction_id=2, reacted_at=FIXED_DT)
        await conn.commit()

    await calculate_user_meme_source_stats()

    stats = await _get_umss(10001, 10001)
    assert stats is not None
    assert stats["nlikes"] == 3
    assert stats["ndislikes"] == 1


@pytest.mark.asyncio
async def test_multiple_sources_separate(setup):
    async with engine.connect() as conn:
        # Reactions to source 10001
        await create_reaction(conn, 10001, 10001, reaction_id=1, reacted_at=FIXED_DT)
        # Reactions to source 10002
        await create_reaction(conn, 10001, 10005, reaction_id=2, reacted_at=FIXED_DT)
        await conn.commit()

    await calculate_user_meme_source_stats()

    stats_s1 = await _get_umss(10001, 10001)
    stats_s2 = await _get_umss(10001, 10002)
    assert stats_s1 is not None
    assert stats_s2 is not None
    assert stats_s1["nlikes"] == 1
    assert stats_s1["ndislikes"] == 0
    assert stats_s2["nlikes"] == 0
    assert stats_s2["ndislikes"] == 1


@pytest.mark.asyncio
async def test_ignores_unreacted(setup):
    async with engine.connect() as conn:
        # reaction_id=None means user hasn't reacted yet (just sent)
        await create_reaction(conn, 10001, 10001, reaction_id=None, reacted_at=None)
        await create_reaction(conn, 10001, 10002, reaction_id=1, reacted_at=FIXED_DT)
        await conn.commit()

    await calculate_user_meme_source_stats()

    stats = await _get_umss(10001, 10001)
    assert stats is not None
    assert stats["nlikes"] == 1
    assert stats["ndislikes"] == 0


@pytest.mark.asyncio
async def test_updates_on_rerun(setup):
    async with engine.connect() as conn:
        await create_reaction(conn, 10001, 10001, reaction_id=1, reacted_at=FIXED_DT)
        await conn.commit()

    await calculate_user_meme_source_stats()
    stats = await _get_umss(10001, 10001)
    assert stats["nlikes"] == 1

    # Add more reactions and rerun
    async with engine.connect() as conn:
        await create_reaction(conn, 10001, 10002, reaction_id=1, reacted_at=FIXED_DT)
        await create_reaction(conn, 10001, 10003, reaction_id=2, reacted_at=FIXED_DT)
        await conn.commit()

    await calculate_user_meme_source_stats()
    stats = await _get_umss(10001, 10001)
    assert stats["nlikes"] == 2
    assert stats["ndislikes"] == 1


@pytest.mark.asyncio
async def test_multiple_users_independent(setup):
    async with engine.connect() as conn:
        await create_reaction(conn, 10001, 10001, reaction_id=1, reacted_at=FIXED_DT)
        await create_reaction(conn, 10002, 10001, reaction_id=2, reacted_at=FIXED_DT)
        await conn.commit()

    await calculate_user_meme_source_stats()

    stats_u1 = await _get_umss(10001, 10001)
    stats_u2 = await _get_umss(10002, 10001)
    assert stats_u1["nlikes"] == 1
    assert stats_u1["ndislikes"] == 0
    assert stats_u2["nlikes"] == 0
    assert stats_u2["ndislikes"] == 1
