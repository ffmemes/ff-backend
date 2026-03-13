"""Tests for reaction service DB functions."""

from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from tests.factories import (
    cleanup_test_data,
    create_meme,
    create_meme_source,
    create_user,
    create_user_language,
)

from src.database import engine, user_meme_reaction
from src.recommendations.service import (
    create_user_meme_reaction,
    update_user_meme_reaction,
    user_meme_reaction_exists,
)


@pytest_asyncio.fixture(loop_scope="session")
async def setup():
    async with engine.connect() as conn:
        await create_user(conn, id=10001)
        await create_user_language(conn, user_id=10001)
        await create_meme_source(conn, id=10001)
        await create_meme(conn, id=10001, meme_source_id=10001)
        await create_meme(conn, id=10002, meme_source_id=10001)
        await create_meme(conn, id=10003, meme_source_id=10001)
        await conn.commit()

    yield

    async with engine.connect() as conn:
        await cleanup_test_data(conn)


async def _get_reaction(user_id: int, meme_id: int) -> dict | None:
    async with engine.connect() as conn:
        row = await conn.execute(
            select(user_meme_reaction).where(
                user_meme_reaction.c.user_id == user_id,
                user_meme_reaction.c.meme_id == meme_id,
            )
        )
        result = row.first()
        return result._asdict() if result else None


@pytest.mark.asyncio
async def test_create_reaction_inserts_record(setup):
    await create_user_meme_reaction(10001, 10001, "test_engine")
    row = await _get_reaction(10001, 10001)
    assert row is not None
    assert row["user_id"] == 10001
    assert row["meme_id"] == 10001
    assert row["recommended_by"] == "test_engine"


@pytest.mark.asyncio
async def test_create_reaction_sets_null_reaction_id(setup):
    await create_user_meme_reaction(10001, 10001, "test")
    row = await _get_reaction(10001, 10001)
    assert row["reaction_id"] is None


@pytest.mark.asyncio
async def test_create_reaction_with_explicit_reaction_id(setup):
    await create_user_meme_reaction(
        10001, 10001, "test", reaction_id=1, reacted_at=datetime.utcnow()
    )
    row = await _get_reaction(10001, 10001)
    assert row["reaction_id"] == 1


@pytest.mark.asyncio
async def test_create_reaction_duplicate_is_silent(setup):
    await create_user_meme_reaction(10001, 10001, "test")
    await create_user_meme_reaction(10001, 10001, "different_engine")
    row = await _get_reaction(10001, 10001)
    assert row["recommended_by"] == "test"


@pytest.mark.asyncio
async def test_update_reaction_returns_true_on_new(setup):
    await create_user_meme_reaction(10001, 10001, "test")
    result = await update_user_meme_reaction(10001, 10001, reaction_id=1)
    assert result is True


@pytest.mark.asyncio
async def test_update_reaction_returns_false_on_duplicate(setup):
    await create_user_meme_reaction(10001, 10001, "test")
    await update_user_meme_reaction(10001, 10001, reaction_id=1)
    result = await update_user_meme_reaction(10001, 10001, reaction_id=2)
    assert result is False


@pytest.mark.asyncio
async def test_update_reaction_sets_reacted_at(setup):
    await create_user_meme_reaction(10001, 10001, "test")
    await update_user_meme_reaction(10001, 10001, reaction_id=1)
    row = await _get_reaction(10001, 10001)
    assert row["reacted_at"] is not None
    assert isinstance(row["reacted_at"], datetime)


@pytest.mark.asyncio
async def test_update_reaction_does_not_overwrite(setup):
    await create_user_meme_reaction(
        10001, 10001, "test", reaction_id=1, reacted_at=datetime.utcnow()
    )
    result = await update_user_meme_reaction(10001, 10001, reaction_id=2)
    assert result is False
    row = await _get_reaction(10001, 10001)
    assert row["reaction_id"] == 1


@pytest.mark.asyncio
async def test_reaction_exists_true(setup):
    await create_user_meme_reaction(10001, 10001, "test")
    assert await user_meme_reaction_exists(10001, 10001) is True


@pytest.mark.asyncio
async def test_reaction_exists_false(setup):
    assert await user_meme_reaction_exists(10001, 10002) is False
