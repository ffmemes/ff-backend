from datetime import datetime, timedelta, timezone

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
    create_user_meme_source_stats,
)

from src.database import engine
from src.recommendations.candidates import get_fresh_viral
from src.recommendations.pipeline import _BAD_FRESH_QUERY, _low_sent_query

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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _fresh_meme(conn, meme_id, source_id, nlikes, ndislikes, created_at=None):
    await create_meme(
        conn,
        id=meme_id,
        meme_source_id=source_id,
        created_at=created_at or _utcnow() - timedelta(hours=1),
    )
    await create_meme_stats(
        conn,
        meme_id=meme_id,
        nlikes=nlikes,
        ndislikes=ndislikes,
        nmemes_sent=nlikes + ndislikes,
    )


@pytest.mark.asyncio
async def test_explore_budget_low_sent_is_fresh_unlabeled_and_demotes_disliked_sources(
    conn: AsyncConnection,
) -> None:
    disliked_source = LOW_SENT_SOURCE_ID + 1
    await create_user(conn, id=LOW_SENT_USER_ID, type="moderator")
    await create_user_language(conn, user_id=LOW_SENT_USER_ID)
    await create_meme_source(conn, id=LOW_SENT_SOURCE_ID)
    await create_meme_source(conn, id=disliked_source)
    await create_user_meme_source_stats(
        conn, user_id=LOW_SENT_USER_ID, meme_source_id=disliked_source, nlikes=1, ndislikes=9
    )
    await _fresh_meme(conn, 10031, LOW_SENT_SOURCE_ID, 0, 0)
    await _fresh_meme(conn, 10032, LOW_SENT_SOURCE_ID, 0, 0, created_at=datetime(2024, 6, 1))
    await _fresh_meme(conn, 10033, LOW_SENT_SOURCE_ID, 10, 10)  # labeled (>= 20)
    await _fresh_meme(conn, 10034, LOW_SENT_SOURCE_ID, 1, 9)  # early-stop: 2/12 < 0.25
    await _fresh_meme(conn, 10035, LOW_SENT_SOURCE_ID, 3, 7)  # 4/12 >= 0.25
    await _fresh_meme(conn, 10036, disliked_source, 0, 0)
    await conn.commit()

    rows = await conn.execute(
        text(_low_sent_query([], explore_budget=True)),
        {"user_id": LOW_SENT_USER_ID, "limit": 10},
    )

    assert [row.id for row in rows] == [10031, 10035, 10036]


@pytest.mark.asyncio
async def test_fresh_viral_and_bad_fresh_rules(conn: AsyncConnection) -> None:
    await create_user(conn, id=LOW_SENT_USER_ID)
    await create_user_language(conn, user_id=LOW_SENT_USER_ID)
    await create_meme_source(conn, id=LOW_SENT_SOURCE_ID)
    four_days_ago = _utcnow() - timedelta(days=4)
    await _fresh_meme(conn, 10041, LOW_SENT_SOURCE_ID, 12, 8)  # viral: 20 reacts, 0.60
    await _fresh_meme(conn, 10042, LOW_SENT_SOURCE_ID, 7, 13)  # bad fresh: 0.35
    await _fresh_meme(conn, 10043, LOW_SENT_SOURCE_ID, 12, 8, created_at=four_days_ago)
    await _fresh_meme(conn, 10044, LOW_SENT_SOURCE_ID, 7, 3)  # too few reactions
    await _fresh_meme(conn, 10045, LOW_SENT_SOURCE_ID, 7, 13, created_at=datetime(2024, 6, 1))
    await conn.commit()

    viral = await get_fresh_viral(LOW_SENT_USER_ID, limit=10)
    bad = await conn.execute(
        text(_BAD_FRESH_QUERY), {"meme_ids": [10041, 10042, 10043, 10044, 10045]}
    )

    assert [(row["id"], row["recommended_by"]) for row in viral] == [(10041, "fresh_viral")]
    assert [row.id for row in bad] == [10042]
