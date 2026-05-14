from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from src.database import engine, fetch_one, meme, meme_raw_telegram, meme_source
from src.storage.constants import MemeSourceStatus
from src.storage.etl import etl_memes_from_raw_telegram_posts, insert_parsed_posts_from_telegram
from src.storage.parsers.schemas import TgChannelPostParsingResult
from tests.factories import TEST_ID_START, cleanup_test_data, create_meme_source

IN_MODERATION_SOURCE_ID = TEST_ID_START + 2100
ENABLED_SOURCE_ID = TEST_ID_START + 2101
MALFORMED_SOURCE_ID = TEST_ID_START + 2102


def _post(source_id: int, post_id: int) -> TgChannelPostParsingResult:
    return TgChannelPostParsingResult(
        post_id=post_id,
        url=f"https://t.me/test_source_{source_id}/{post_id}",
        content="мем дня",
        media=[{"url": "https://example.com/meme.jpg"}],
        views=100,
        date=datetime.utcnow(),
    )


@pytest_asyncio.fixture()
async def conn():
    async with engine.connect() as conn:
        yield conn
        await conn.execute(
            delete(meme_source).where(
                meme_source.c.id.in_([IN_MODERATION_SOURCE_ID, ENABLED_SOURCE_ID])
            )
        )
        await conn.commit()
        await cleanup_test_data(conn)


@pytest.mark.asyncio
async def test_telegram_etl_skips_raw_posts_from_in_moderation_source(
    conn: AsyncConnection,
):
    await create_meme_source(
        conn,
        id=IN_MODERATION_SOURCE_ID,
        status=MemeSourceStatus.IN_MODERATION.value,
    )
    await conn.commit()

    await insert_parsed_posts_from_telegram(
        IN_MODERATION_SOURCE_ID,
        [_post(IN_MODERATION_SOURCE_ID, 3001)],
        discover_candidates=False,
    )
    await etl_memes_from_raw_telegram_posts()

    row = await fetch_one(
        select(func.count().label("n"))
        .select_from(meme)
        .where(meme.c.meme_source_id == IN_MODERATION_SOURCE_ID)
    )
    assert row["n"] == 0


@pytest.mark.asyncio
async def test_telegram_etl_processes_raw_posts_from_enabled_source(
    conn: AsyncConnection,
):
    await create_meme_source(
        conn,
        id=ENABLED_SOURCE_ID,
        status=MemeSourceStatus.PARSING_ENABLED.value,
    )
    await conn.commit()

    await insert_parsed_posts_from_telegram(
        ENABLED_SOURCE_ID,
        [_post(ENABLED_SOURCE_ID, 3002)],
        discover_candidates=False,
    )
    await etl_memes_from_raw_telegram_posts()

    created = await fetch_one(select(meme).where(meme.c.meme_source_id == ENABLED_SOURCE_ID))
    assert created is not None
    assert created["status"] == "created"


@pytest.mark.asyncio
async def test_telegram_etl_ignores_malformed_media_rows(conn: AsyncConnection):
    await create_meme_source(
        conn,
        id=MALFORMED_SOURCE_ID,
        status=MemeSourceStatus.PARSING_ENABLED.value,
    )
    await conn.execute(
        insert(meme_raw_telegram).values(
            meme_source_id=MALFORMED_SOURCE_ID,
            post_id=3003,
            url="https://t.me/malformed/3003",
            date=datetime.utcnow(),
            content="мем дня",
            media={"url": "https://example.com/not-array.jpg"},
            out_links={"url": "https://example.com"},
            views=100,
        )
    )
    await conn.commit()

    await etl_memes_from_raw_telegram_posts()

    created = await fetch_one(select(meme).where(meme.c.meme_source_id == MALFORMED_SOURCE_ID))
    assert created is None
