"""Integration tests for maybe_auto_snooze_source."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncConnection

from src.database import engine, fetch_one, meme_source
from src.storage.constants import MemeSourceStatus
from src.storage.service import maybe_auto_snooze_source
from tests.factories import (
    TEST_ID_START,
    cleanup_test_data,
    create_meme_source,
    create_meme_source_stats,
)


@pytest_asyncio.fixture()
async def conn():
    async with engine.connect() as conn:
        yield conn
        await cleanup_test_data(conn)


SOURCE_ID = TEST_ID_START + 500


@pytest.mark.asyncio
async def test_no_snooze_on_first_empty_parse(conn: AsyncConnection):
    await create_meme_source(conn, id=SOURCE_ID, status="parsing_enabled")
    await conn.commit()

    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=0)
    assert result is None

    source = await fetch_one(meme_source.select().where(meme_source.c.id == SOURCE_ID))
    assert source["status"] == MemeSourceStatus.PARSING_ENABLED.value
    assert source["data"]["consecutive_empty_parses"] == 1


@pytest.mark.asyncio
async def test_no_snooze_on_second_empty_parse(conn: AsyncConnection):
    await create_meme_source(conn, id=SOURCE_ID, status="parsing_enabled")
    await conn.commit()

    await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=0)
    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=0)
    assert result is None

    source = await fetch_one(meme_source.select().where(meme_source.c.id == SOURCE_ID))
    assert source["status"] == MemeSourceStatus.PARSING_ENABLED.value
    assert source["data"]["consecutive_empty_parses"] == 2


@pytest.mark.asyncio
async def test_snooze_on_third_consecutive_empty_parse(conn: AsyncConnection):
    await create_meme_source(conn, id=SOURCE_ID, status="parsing_enabled")
    await conn.commit()

    await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=0)
    await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=0)
    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=0)

    assert result == "no_posts_3x"
    source = await fetch_one(meme_source.select().where(meme_source.c.id == SOURCE_ID))
    assert source["status"] == MemeSourceStatus.SNOOZED.value
    assert source["data"]["snoozed_reason"] == "no_posts_3x"
    assert "snoozed_at" in source["data"]


@pytest.mark.asyncio
async def test_counter_resets_after_successful_parse(conn: AsyncConnection):
    await create_meme_source(conn, id=SOURCE_ID, status="parsing_enabled")
    await conn.commit()

    await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=0)
    await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=0)
    # successful parse resets counter
    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=5)
    assert result is None

    source = await fetch_one(meme_source.select().where(meme_source.c.id == SOURCE_ID))
    assert source["status"] == MemeSourceStatus.PARSING_ENABLED.value
    assert source["data"]["consecutive_empty_parses"] == 0

    # subsequent empty parses start from 1 again
    await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=0)
    await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=0)
    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=0)
    assert result == "no_posts_3x"


@pytest.mark.asyncio
async def test_snooze_on_low_like_rate(conn: AsyncConnection):
    await create_meme_source(conn, id=SOURCE_ID, status="parsing_enabled")
    # 5% like rate with 200 total reactions → should snooze
    await create_meme_source_stats(
        conn,
        meme_source_id=SOURCE_ID,
        nlikes=10,
        ndislikes=190,
        nmemes_sent=200,
    )
    await conn.commit()

    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=5)

    assert result == "low_like_rate"
    source = await fetch_one(meme_source.select().where(meme_source.c.id == SOURCE_ID))
    assert source["status"] == MemeSourceStatus.SNOOZED.value
    assert source["data"]["snoozed_reason"] == "low_like_rate"


@pytest.mark.asyncio
async def test_no_snooze_on_acceptable_like_rate(conn: AsyncConnection):
    await create_meme_source(conn, id=SOURCE_ID, status="parsing_enabled")
    # 50% like rate → healthy, no snooze
    await create_meme_source_stats(
        conn,
        meme_source_id=SOURCE_ID,
        nlikes=100,
        ndislikes=100,
        nmemes_sent=200,
    )
    await conn.commit()

    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=5)
    assert result is None

    source = await fetch_one(meme_source.select().where(meme_source.c.id == SOURCE_ID))
    assert source["status"] == MemeSourceStatus.PARSING_ENABLED.value


@pytest.mark.asyncio
async def test_no_snooze_when_below_min_reactions(conn: AsyncConnection):
    await create_meme_source(conn, id=SOURCE_ID, status="parsing_enabled")
    # 5% like rate but only 40 reactions → not enough data, no snooze
    await create_meme_source_stats(
        conn,
        meme_source_id=SOURCE_ID,
        nlikes=2,
        ndislikes=38,
        nmemes_sent=40,
    )
    await conn.commit()

    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=5)
    assert result is None


@pytest.mark.asyncio
async def test_already_snoozed_source_skipped(conn: AsyncConnection):
    await create_meme_source(conn, id=SOURCE_ID, status="snoozed")
    await conn.commit()

    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=0)
    assert result is None
