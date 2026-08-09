"""VK ETL parity with Telegram: parsing_enabled gate + quality windows."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from src.database import engine, fetch_one, meme, meme_raw_vk, meme_source
from src.storage import etl as vk_etl
from src.storage.constants import MemeSourceStatus, MemeSourceType
from src.storage.etl import etl_memes_from_raw_vk_posts, insert_parsed_posts_from_vk
from src.storage.parsers.schemas import VkGroupPostParsingResult
from src.storage.service import get_unloaded_vk_memes
from tests.factories import TEST_ID_START, cleanup_test_data, create_meme_source

IN_MODERATION_SOURCE_ID = TEST_ID_START + 3100
ENABLED_SOURCE_ID = TEST_ID_START + 3101
TOP_VIEWED_SOURCE_ID = TEST_ID_START + 3102


def _vk_post(
    source_id: int,
    post_id: str,
    *,
    views: int = 100,
    date: datetime | None = None,
    media: list[str] | None = None,
) -> VkGroupPostParsingResult:
    return VkGroupPostParsingResult(
        post_id=post_id,
        url=f"https://vk.com/wall-{source_id}_{post_id}",
        content="мем",
        media=media or [f"https://example.com/vk_{post_id}.jpg"],
        date=date or datetime.utcnow(),
        views=views,
        likes=10,
        reposts=1,
        comments=0,
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
                        TOP_VIEWED_SOURCE_ID,
                    ]
                )
            )
        )
        await conn.commit()
        await cleanup_test_data(conn)


@pytest.mark.asyncio
async def test_vk_etl_sql_requires_parsing_enabled(monkeypatch):
    captured = []

    async def fake_fetch_all(query, params=None):
        captured.append((str(query), params))
        return []

    async def fake_update_or_create(transformed, missing):
        return None

    monkeypatch.setattr(vk_etl, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(vk_etl, "update_or_create_memes", fake_update_or_create)

    await etl_memes_from_raw_vk_posts(fresh_only=True)

    transform_sql, transform_params = captured[0]
    assert "MS.status = 'parsing_enabled'" in transform_sql
    assert "top_viewed_recent_posts" in transform_sql
    assert transform_params["fresh_only"] is True


@pytest.mark.asyncio
async def test_vk_etl_skips_in_moderation_source(conn: AsyncConnection):
    await create_meme_source(
        conn,
        id=IN_MODERATION_SOURCE_ID,
        type=MemeSourceType.VK.value,
        url=f"https://vk.com/club{IN_MODERATION_SOURCE_ID}",
        status=MemeSourceStatus.IN_MODERATION.value,
    )
    await conn.commit()

    await insert_parsed_posts_from_vk(
        IN_MODERATION_SOURCE_ID,
        [_vk_post(IN_MODERATION_SOURCE_ID, "5001")],
    )
    await etl_memes_from_raw_vk_posts()

    row = await fetch_one(
        select(func.count().label("n"))
        .select_from(meme)
        .where(meme.c.meme_source_id == IN_MODERATION_SOURCE_ID)
    )
    assert row["n"] == 0


@pytest.mark.asyncio
async def test_vk_etl_processes_enabled_source(conn: AsyncConnection):
    await create_meme_source(
        conn,
        id=ENABLED_SOURCE_ID,
        type=MemeSourceType.VK.value,
        url=f"https://vk.com/club{ENABLED_SOURCE_ID}",
        status=MemeSourceStatus.PARSING_ENABLED.value,
    )
    await conn.commit()

    await insert_parsed_posts_from_vk(
        ENABLED_SOURCE_ID,
        [_vk_post(ENABLED_SOURCE_ID, "5002", views=200)],
    )
    await etl_memes_from_raw_vk_posts()

    created = await fetch_one(select(meme).where(meme.c.meme_source_id == ENABLED_SOURCE_ID))
    assert created is not None
    assert created["status"] == "created"


@pytest.mark.asyncio
async def test_vk_etl_promotes_top_five_views_from_latest_ten(conn: AsyncConnection):
    await create_meme_source(
        conn,
        id=TOP_VIEWED_SOURCE_ID,
        type=MemeSourceType.VK.value,
        url=f"https://vk.com/club{TOP_VIEWED_SOURCE_ID}",
        status=MemeSourceStatus.PARSING_ENABLED.value,
    )
    await conn.commit()

    base = datetime(2026, 1, 1, 12, 0, 0)
    posts = [
        _vk_post(TOP_VIEWED_SOURCE_ID, "6001", views=9999, date=base),
        _vk_post(TOP_VIEWED_SOURCE_ID, "6002", views=8888, date=base + timedelta(minutes=1)),
        _vk_post(TOP_VIEWED_SOURCE_ID, "6003", views=10, date=base + timedelta(minutes=2)),
        _vk_post(TOP_VIEWED_SOURCE_ID, "6004", views=900, date=base + timedelta(minutes=3)),
        _vk_post(TOP_VIEWED_SOURCE_ID, "6005", views=30, date=base + timedelta(minutes=4)),
        _vk_post(TOP_VIEWED_SOURCE_ID, "6006", views=800, date=base + timedelta(minutes=5)),
        _vk_post(TOP_VIEWED_SOURCE_ID, "6007", views=40, date=base + timedelta(minutes=6)),
        _vk_post(TOP_VIEWED_SOURCE_ID, "6008", views=700, date=base + timedelta(minutes=7)),
        _vk_post(TOP_VIEWED_SOURCE_ID, "6009", views=50, date=base + timedelta(minutes=8)),
        _vk_post(TOP_VIEWED_SOURCE_ID, "6010", views=600, date=base + timedelta(minutes=9)),
        _vk_post(TOP_VIEWED_SOURCE_ID, "6011", views=60, date=base + timedelta(minutes=10)),
        _vk_post(TOP_VIEWED_SOURCE_ID, "6012", views=500, date=base + timedelta(minutes=11)),
    ]
    await insert_parsed_posts_from_vk(TOP_VIEWED_SOURCE_ID, posts)
    await etl_memes_from_raw_vk_posts([TOP_VIEWED_SOURCE_ID], fresh_only=False)

    created = await fetch_one(
        select(func.count().label("n"))
        .select_from(meme)
        .where(meme.c.meme_source_id == TOP_VIEWED_SOURCE_ID)
    )
    rows = await conn.execute(
        select(meme_raw_vk.c.post_id)
        .select_from(meme)
        .join(
            meme_raw_vk,
            (meme_raw_vk.c.id == meme.c.raw_meme_id)
            & (meme_raw_vk.c.meme_source_id == meme.c.meme_source_id),
        )
        .where(meme.c.meme_source_id == TOP_VIEWED_SOURCE_ID)
        .order_by(meme_raw_vk.c.post_id)
    )

    assert created["n"] == 5
    assert [row.post_id for row in rows] == ["6004", "6006", "6008", "6010", "6012"]


@pytest.mark.asyncio
async def test_get_unloaded_vk_requires_parsing_enabled(monkeypatch):
    captured = []

    async def fake_fetch_all(query, params=None):
        captured.append((str(query), params))
        return []

    monkeypatch.setattr("src.storage.service.fetch_all", fake_fetch_all)
    await get_unloaded_vk_memes(limit=10)

    sql, params = captured[0]
    assert "parsing_enabled" in sql
    assert "broken_content_link" in sql
    assert params["fresh_only"] is True


@pytest.mark.asyncio
async def test_parse_vk_source_calls_auto_snooze(monkeypatch):
    from src.flows.parsers import vk as vk_flow

    posts = [_vk_post(1, "1")]
    scraper = AsyncMock()
    scraper.get_items = AsyncMock(return_value=posts)
    monkeypatch.setattr(vk_flow, "VkGroupScraper", lambda url: scraper)
    monkeypatch.setattr(vk_flow, "insert_parsed_posts_from_vk", AsyncMock())
    monkeypatch.setattr(vk_flow, "update_meme_source", AsyncMock())
    monkeypatch.setattr(vk_flow, "maybe_auto_snooze_source", AsyncMock(return_value=None))
    monkeypatch.setattr(vk_flow, "get_run_logger", lambda: MagicMock())
    monkeypatch.setattr(vk_flow.asyncio, "sleep", AsyncMock())

    # prefect flow wrapper — call underlying function if needed
    fn = getattr(vk_flow.parse_vk_source, "fn", vk_flow.parse_vk_source)
    await fn(42, "https://vk.com/club42", nposts=5)

    vk_flow.maybe_auto_snooze_source.assert_awaited_once_with(42, 1)
    vk_flow.insert_parsed_posts_from_vk.assert_awaited_once()
