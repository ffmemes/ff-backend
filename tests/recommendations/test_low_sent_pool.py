import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.factories import (
    cleanup_test_data,
    create_meme,
    create_meme_source,
    create_meme_stats,
    create_user,
    create_user_language,
)

from src.database import engine
from src.recommendations.pipeline import _low_sent_query

LOW_SENT_USER_ID = 10020
LOW_SENT_SOURCE_ID = 10020


@pytest_asyncio.fixture()
async def conn():
    async with engine.connect() as conn:
        await cleanup_test_data(conn)
        yield conn
        await cleanup_test_data(conn)


async def _create_low_sent_meme(
    conn: AsyncConnection,
    meme_id: int,
    *,
    nlikes: int,
    ndislikes: int,
    nmemes_sent: int,
) -> None:
    await create_meme(conn, id=meme_id, meme_source_id=LOW_SENT_SOURCE_ID)
    await create_meme_stats(
        conn,
        meme_id=meme_id,
        nlikes=nlikes,
        ndislikes=ndislikes,
        nmemes_sent=nmemes_sent,
    )


@pytest.mark.asyncio
async def test_low_sent_pool_prioritizes_unreacted_memes_and_filters_failed_memes(
    conn: AsyncConnection,
) -> None:
    await create_user(conn, id=LOW_SENT_USER_ID, type="moderator")
    await create_user_language(conn, user_id=LOW_SENT_USER_ID)
    await create_meme_source(conn, id=LOW_SENT_SOURCE_ID)
    await _create_low_sent_meme(conn, 10021, nlikes=0, ndislikes=0, nmemes_sent=0)
    await _create_low_sent_meme(conn, 10022, nlikes=1, ndislikes=0, nmemes_sent=1)
    await _create_low_sent_meme(conn, 10023, nlikes=0, ndislikes=9, nmemes_sent=9)
    await _create_low_sent_meme(conn, 10024, nlikes=0, ndislikes=10, nmemes_sent=10)
    await _create_low_sent_meme(conn, 10025, nlikes=2, ndislikes=8, nmemes_sent=10)
    await conn.commit()

    rows = await conn.execute(
        text(_low_sent_query([])),
        {"user_id": LOW_SENT_USER_ID, "limit": 10},
    )
    ids = [row.id for row in rows]

    assert ids[:3] == [10021, 10022, 10023]
    assert 10024 not in ids
    assert 10025 in ids
