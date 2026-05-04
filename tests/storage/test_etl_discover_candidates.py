"""Integration tests for discover_source_candidates_from_telegram_posts.

Covers the FFM-936 review fixes:
- Re-parsing the same post must NOT re-increment `times_forwarded`.
- The sample columns must store `(meme_source_id, post_id)`, not the autoincrement
  `meme_raw_telegram.id`.
"""

from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncConnection

from src.database import (
    engine,
    fetch_one,
    meme_source_candidate,
)
from src.storage.etl import insert_parsed_posts_from_telegram
from src.storage.parsers.schemas import TgChannelPostParsingResult
from tests.factories import TEST_ID_START, cleanup_test_data, create_meme_source

PARSING_SOURCE_ID = TEST_ID_START + 600
DISCOVERED_CANDIDATE_URL = "https://t.me/ffm936_discovered_channel"


def _post(post_id: int, forwarded_url: str | None) -> TgChannelPostParsingResult:
    return TgChannelPostParsingResult(
        post_id=post_id,
        url=f"https://t.me/test_source_{PARSING_SOURCE_ID}/{post_id}",
        content="hello",
        media=[{"url": "https://example.com/x.jpg"}],
        views=100,
        date=datetime(2024, 6, 1, 12, 0, 0),
        forwarded_url=forwarded_url,
    )


@pytest_asyncio.fixture()
async def conn():
    async with engine.connect() as conn:
        yield conn
        await conn.execute(
            delete(meme_source_candidate).where(
                meme_source_candidate.c.url == DISCOVERED_CANDIDATE_URL
            )
        )
        await conn.commit()
        await cleanup_test_data(conn)


@pytest.mark.asyncio
async def test_reparsing_same_post_does_not_double_count_times_forwarded(
    conn: AsyncConnection,
):
    await create_meme_source(conn, id=PARSING_SOURCE_ID, status="parsing_enabled")
    await conn.commit()

    posts = [_post(post_id=1001, forwarded_url=DISCOVERED_CANDIDATE_URL)]

    # First parse: fresh insert → candidate counted once.
    await insert_parsed_posts_from_telegram(PARSING_SOURCE_ID, posts)
    # Second parse of the *same* post (e.g. the next hourly cron picking it up
    # again because views/content shifted) must NOT bump the counter again.
    await insert_parsed_posts_from_telegram(PARSING_SOURCE_ID, posts)

    candidate = await fetch_one(
        select(meme_source_candidate).where(meme_source_candidate.c.url == DISCOVERED_CANDIDATE_URL)
    )
    assert candidate is not None
    assert candidate["times_forwarded"] == 1
    assert candidate["sample_meme_source_id"] == PARSING_SOURCE_ID
    assert candidate["sample_meme_raw_telegram_post_id"] == 1001


@pytest.mark.asyncio
async def test_new_distinct_posts_increment_times_forwarded(conn: AsyncConnection):
    await create_meme_source(conn, id=PARSING_SOURCE_ID, status="parsing_enabled")
    await conn.commit()

    await insert_parsed_posts_from_telegram(
        PARSING_SOURCE_ID,
        [_post(post_id=2001, forwarded_url=DISCOVERED_CANDIDATE_URL)],
    )
    await insert_parsed_posts_from_telegram(
        PARSING_SOURCE_ID,
        [
            # 2001 already in DB → should be skipped by discovery.
            _post(post_id=2001, forwarded_url=DISCOVERED_CANDIDATE_URL),
            _post(post_id=2002, forwarded_url=DISCOVERED_CANDIDATE_URL),
            _post(post_id=2003, forwarded_url=DISCOVERED_CANDIDATE_URL),
        ],
    )

    candidate = await fetch_one(
        select(meme_source_candidate).where(meme_source_candidate.c.url == DISCOVERED_CANDIDATE_URL)
    )
    assert candidate is not None
    # 1 from first batch + 2 newly inserted on second batch = 3.
    assert candidate["times_forwarded"] == 3
