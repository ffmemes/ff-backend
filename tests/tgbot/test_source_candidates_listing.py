"""Tests for list_pending_source_candidates filtering (FFM-938).

Discovery's own dedup only fires at INSERT time, so a candidate URL that gets
manually added to meme_source via the existing URL flow leaves a stale
`discovered` row that would re-surface in /discoveredsources forever without
the listing-time filter under test here.
"""

from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.factories import TEST_ID_START, cleanup_test_data, create_meme_source

from src.database import engine, meme_source_candidate
from src.tgbot.service import list_pending_source_candidates

ORPHAN_CANDIDATE_URL = "https://t.me/ffm938_orphan_candidate"
PROMOTED_CANDIDATE_URL = "https://t.me/ffm938_promoted_candidate"
PROMOTED_SOURCE_ID = TEST_ID_START + 938


async def _create_candidate(conn: AsyncConnection, url: str, times_forwarded: int) -> None:
    await conn.execute(
        insert(meme_source_candidate)
        .values(
            type="telegram",
            url=url,
            status="discovered",
            times_forwarded=times_forwarded,
            created_at=datetime(2024, 6, 1, 12, 0, 0),
            updated_at=datetime(2024, 6, 1, 12, 0, 0),
        )
        .on_conflict_do_nothing()
    )


@pytest_asyncio.fixture()
async def conn():
    async with engine.connect() as conn:
        yield conn
        await conn.execute(
            delete(meme_source_candidate).where(
                meme_source_candidate.c.url.in_([ORPHAN_CANDIDATE_URL, PROMOTED_CANDIDATE_URL])
            )
        )
        await conn.commit()
        await cleanup_test_data(conn)


@pytest.mark.asyncio
async def test_candidate_already_in_meme_source_is_excluded(conn: AsyncConnection):
    # Candidate exists in the discovery queue …
    await _create_candidate(conn, PROMOTED_CANDIDATE_URL, times_forwarded=5)
    # … and the same URL was added to meme_source via the manual URL flow.
    await create_meme_source(conn, id=PROMOTED_SOURCE_ID, url=PROMOTED_CANDIDATE_URL)
    await conn.commit()

    rows = await list_pending_source_candidates(limit=50)

    urls = {row["url"] for row in rows}
    assert PROMOTED_CANDIDATE_URL not in urls


@pytest.mark.asyncio
async def test_candidate_without_meme_source_match_is_returned(conn: AsyncConnection):
    await _create_candidate(conn, ORPHAN_CANDIDATE_URL, times_forwarded=3)
    await conn.commit()

    rows = await list_pending_source_candidates(limit=50)

    urls = {row["url"] for row in rows}
    assert ORPHAN_CANDIDATE_URL in urls
