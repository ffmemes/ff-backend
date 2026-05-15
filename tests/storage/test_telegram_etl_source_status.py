from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from src.database import engine, fetch_one, meme, meme_raw_telegram, meme_source
from src.storage import etl as telegram_etl
from src.storage.constants import MemeSourceStatus
from src.storage.etl import etl_memes_from_raw_telegram_posts, insert_parsed_posts_from_telegram
from src.storage.parsers.schemas import TgChannelPostParsingResult
from tests.factories import TEST_ID_START, cleanup_test_data, create_meme_source

IN_MODERATION_SOURCE_ID = TEST_ID_START + 2100
ENABLED_SOURCE_ID = TEST_ID_START + 2101
MALFORMED_SOURCE_ID = TEST_ID_START + 2102
TOP_VIEWED_SOURCE_ID = TEST_ID_START + 2103


def _post(
    source_id: int,
    post_id: int,
    *,
    views: int = 100,
    date: datetime | None = None,
) -> TgChannelPostParsingResult:
    return TgChannelPostParsingResult(
        post_id=post_id,
        url=f"https://t.me/test_source_{source_id}/{post_id}",
        content="мем дня",
        media=[{"url": "https://example.com/meme.jpg"}],
        views=views,
        date=date or datetime.utcnow(),
    )


@pytest_asyncio.fixture()
async def conn():
    async with engine.connect() as conn:
        yield conn
        await conn.execute(
            delete(meme_source).where(
                meme_source.c.id.in_(
                    [
                        IN_MODERATION_SOURCE_ID,
                        ENABLED_SOURCE_ID,
                        MALFORMED_SOURCE_ID,
                        TOP_VIEWED_SOURCE_ID,
                    ]
                )
            )
        )
        await conn.commit()
        await cleanup_test_data(conn)


@pytest.mark.asyncio
async def test_telegram_etl_applies_freshness_before_top_view_ranking(monkeypatch):
    captured_queries = []

    async def fake_fetch_all(query, params=None):
        captured_queries.append((str(query), params))
        return []

    async def fake_update_or_create_memes(transformed_memes, memes_not_in_memes_table):
        return None

    monkeypatch.setattr(telegram_etl, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(telegram_etl, "update_or_create_memes", fake_update_or_create_memes)

    await etl_memes_from_raw_telegram_posts(fresh_only=True)

    transform_query, transform_params = captured_queries[0]
    latest_source_posts_query = transform_query.split("latest_source_posts AS (", 1)[1].split(
        "),\n                top_viewed_recent_posts", 1
    )[0]

    assert transform_params["fresh_only"] is True
    assert "NOT :fresh_only" in latest_source_posts_query
    assert "COALESCE(MRT.updated_at, MRT.created_at) >= NOW() - INTERVAL '24 hours'" in (
        latest_source_posts_query
    )


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


@pytest.mark.asyncio
async def test_telegram_etl_promotes_top_five_views_from_latest_ten_posts(
    conn: AsyncConnection,
):
    await create_meme_source(
        conn,
        id=TOP_VIEWED_SOURCE_ID,
        status=MemeSourceStatus.PARSING_ENABLED.value,
    )
    await conn.commit()

    base_date = datetime(2026, 1, 1, 12, 0, 0)
    posts = [
        # Older than the latest-10 window: high views must not matter.
        _post(TOP_VIEWED_SOURCE_ID, 4001, views=9999, date=base_date),
        _post(TOP_VIEWED_SOURCE_ID, 4002, views=8888, date=base_date + timedelta(minutes=1)),
        # Latest 10 posts: only the top 5 by views should enter `meme`.
        _post(TOP_VIEWED_SOURCE_ID, 4003, views=10, date=base_date + timedelta(minutes=2)),
        _post(TOP_VIEWED_SOURCE_ID, 4004, views=900, date=base_date + timedelta(minutes=3)),
        _post(TOP_VIEWED_SOURCE_ID, 4005, views=30, date=base_date + timedelta(minutes=4)),
        _post(TOP_VIEWED_SOURCE_ID, 4006, views=800, date=base_date + timedelta(minutes=5)),
        _post(TOP_VIEWED_SOURCE_ID, 4007, views=40, date=base_date + timedelta(minutes=6)),
        _post(TOP_VIEWED_SOURCE_ID, 4008, views=700, date=base_date + timedelta(minutes=7)),
        _post(TOP_VIEWED_SOURCE_ID, 4009, views=50, date=base_date + timedelta(minutes=8)),
        _post(TOP_VIEWED_SOURCE_ID, 4010, views=600, date=base_date + timedelta(minutes=9)),
        _post(TOP_VIEWED_SOURCE_ID, 4011, views=60, date=base_date + timedelta(minutes=10)),
        _post(TOP_VIEWED_SOURCE_ID, 4012, views=500, date=base_date + timedelta(minutes=11)),
    ]

    await insert_parsed_posts_from_telegram(
        TOP_VIEWED_SOURCE_ID,
        posts,
        discover_candidates=False,
    )
    await etl_memes_from_raw_telegram_posts([TOP_VIEWED_SOURCE_ID], fresh_only=False)

    created = await fetch_one(
        select(func.count().label("n"))
        .select_from(meme)
        .where(meme.c.meme_source_id == TOP_VIEWED_SOURCE_ID)
    )
    rows = await conn.execute(
        select(meme_raw_telegram.c.post_id)
        .select_from(meme)
        .join(
            meme_raw_telegram,
            (meme_raw_telegram.c.id == meme.c.raw_meme_id)
            & (meme_raw_telegram.c.meme_source_id == meme.c.meme_source_id),
        )
        .where(meme.c.meme_source_id == TOP_VIEWED_SOURCE_ID)
        .order_by(meme_raw_telegram.c.post_id)
    )

    assert created["n"] == 5
    assert [row.post_id for row in rows] == [4004, 4006, 4008, 4010, 4012]
