from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.dialects import postgresql

from src.database import engine
from src.flows.storage import describe_memes_repository as repository
from tests.factories import (
    cleanup_test_data,
    create_meme,
    create_meme_source,
    create_reaction,
    create_user,
)


@pytest_asyncio.fixture()
async def describe_queue_data():
    async with engine.connect() as conn:
        await create_meme_source(conn, id=120000, type="telegram")
        await create_meme_source(
            conn,
            id=120001,
            type="user upload",
            url="https://t.me/test_upload_describe_queue",
        )
        for user_id in range(120000, 120020):
            await create_user(conn, id=user_id)
        await conn.commit()

    yield

    async with engine.connect() as conn:
        await cleanup_test_data(conn)


def test_describe_queue_limits_reserve_recent_delivery_majority_and_fairness():
    assert repository._describe_queue_limits(9) == {
        "recent_served": 5,
        "recent_uploads": 2,
        "fresh": 1,
        "oldest": 1,
    }
    assert repository._describe_queue_limits(30) == {
        "recent_served": 16,
        "recent_uploads": 6,
        "fresh": 5,
        "oldest": 3,
    }


@pytest.mark.asyncio
async def test_get_memes_to_describe_uses_bounded_recent_delivery_tiers(monkeypatch):
    fetch_all = AsyncMock(return_value=[])
    monkeypatch.setattr(repository, "fetch_all", fetch_all)

    assert await repository.get_memes_to_describe(limit=9) == []

    query = fetch_all.await_args.args[0]
    compiled = query.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    params = compiled.params

    assert "meme_stats" not in sql.lower()
    assert "nlikes" not in sql.lower()
    assert "recent_delivery_events" in sql
    assert "LIMIT %(recent_delivery_scan_limit)s" in sql
    assert "ORDER BY R.sent_at DESC" in sql
    assert "NOT EXISTS (SELECT 1 FROM recent_uploads" in sql
    assert "NOT EXISTS (SELECT 1 FROM selected_recent_served" in sql
    assert "selected_active_backfill" in sql
    assert params["recent_delivery_scan_limit"] == 500
    assert params["recent_served_limit"] == 5
    assert params["recent_uploads_limit"] == 2
    assert params["fresh_limit"] == 1
    assert params["oldest_limit"] == 1


@pytest.mark.asyncio
async def test_get_memes_to_describe_reassigns_unused_tier_capacity(monkeypatch):
    fetch_all = AsyncMock(return_value=[])
    monkeypatch.setattr(repository, "fetch_all", fetch_all)

    await repository.get_memes_to_describe(limit=9)

    sql = str(fetch_all.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "- (SELECT COUNT(*) FROM recent_uploads)" in sql
    assert "- (SELECT COUNT(*) FROM selected_recent_served)" in sql
    assert "- (SELECT COUNT(*) FROM selected_fresh)" in sql
    assert "- (SELECT COUNT(*) FROM selected_oldest)" in sql


@pytest.mark.asyncio
async def test_get_memes_to_describe_reserves_tiers_and_excludes_upload_overlap(
    describe_queue_data,
):
    now = datetime.now(UTC).replace(tzinfo=None)
    async with engine.connect() as conn:
        # Upload 120010 is also a recent delivery. It must occupy an upload slot
        # only, leaving all five delivery slots for other images.
        await create_meme(
            conn,
            id=120010,
            meme_source_id=120001,
            created_at=now - timedelta(minutes=30),
        )
        await create_meme(
            conn,
            id=120011,
            meme_source_id=120001,
            created_at=now - timedelta(minutes=20),
        )
        await create_reaction(conn, 120000, 120010, sent_at=now - timedelta(seconds=5))

        recent_served_ids = list(range(120020, 120025))
        for offset, meme_id in enumerate(recent_served_ids, start=1):
            await create_meme(conn, id=meme_id, meme_source_id=120000, created_at=now)
            await create_reaction(
                conn,
                user_id=120000 + offset,
                meme_id=meme_id,
                sent_at=now - timedelta(minutes=offset),
            )

        await create_meme(
            conn,
            id=120030,
            meme_source_id=120000,
            created_at=now - timedelta(hours=2),
        )
        await create_meme(
            conn,
            id=120031,
            meme_source_id=120000,
            created_at=now - timedelta(days=8),
        )
        await conn.commit()

    selected = await repository.get_memes_to_describe(limit=9)

    assert [row["id"] for row in selected] == [
        120011,
        120010,
        *recent_served_ids,
        120030,
        120031,
    ]
    assert len({row["id"] for row in selected}) == 9


@pytest.mark.asyncio
async def test_get_memes_to_describe_reassigns_empty_upload_and_delivery_slots(
    describe_queue_data,
):
    now = datetime.now(UTC).replace(tzinfo=None)
    async with engine.connect() as conn:
        recent_served_ids = list(range(120040, 120043))
        for offset, meme_id in enumerate(recent_served_ids, start=1):
            await create_meme(conn, id=meme_id, meme_source_id=120000, created_at=now)
            await create_reaction(
                conn,
                user_id=120010 + offset,
                meme_id=meme_id,
                sent_at=now - timedelta(minutes=offset),
            )

        fresh_ids = list(range(120050, 120055))
        for offset, meme_id in enumerate(fresh_ids, start=1):
            await create_meme(
                conn,
                id=meme_id,
                meme_source_id=120000,
                created_at=now - timedelta(hours=offset),
            )

        await create_meme(
            conn,
            id=120060,
            meme_source_id=120000,
            created_at=now - timedelta(days=8),
        )
        await conn.commit()

    selected = await repository.get_memes_to_describe(limit=9)

    assert [row["id"] for row in selected] == [
        *recent_served_ids,
        *fresh_ids,
        120060,
    ]


@pytest.mark.asyncio
async def test_get_memes_to_describe_backfills_an_empty_oldest_tier(describe_queue_data):
    now = datetime.now(UTC).replace(tzinfo=None)
    async with engine.connect() as conn:
        recent_served_ids = list(range(120070, 120078))
        for offset, meme_id in enumerate(recent_served_ids, start=1):
            await create_meme(conn, id=meme_id, meme_source_id=120000, created_at=now)
            await create_reaction(
                conn,
                user_id=120010 + offset,
                meme_id=meme_id,
                sent_at=now - timedelta(minutes=offset),
            )

        await create_meme(
            conn,
            id=120080,
            meme_source_id=120000,
            created_at=now - timedelta(hours=2),
        )
        await conn.commit()

    selected = await repository.get_memes_to_describe(limit=9)

    assert [row["id"] for row in selected] == [*recent_served_ids, 120080]


@pytest.mark.parametrize(
    "result",
    [
        {"ocr_text": "visible text", "description": "a meme"},
        {"ocr_text": "visible text", "description": "a meme", "language": None},
        {"ocr_text": None, "description": {"unexpected": "object"}, "language": 123},
    ],
)
@pytest.mark.asyncio
async def test_save_meme_description_normalizes_missing_or_non_string_fields(monkeypatch, result):
    fetch_one = AsyncMock(return_value={})
    monkeypatch.setattr(repository, "fetch_one", fetch_one)
    result["__model"] = "test-model:free"

    merged = await repository.save_meme_description(
        42,
        {},
        result,
    )

    update_query = fetch_one.await_args.args[0]
    update_params = update_query.compile(dialect=postgresql.dialect()).params

    assert isinstance(merged["text"], str)
    assert isinstance(merged["description"], str)
    assert merged["raw_result"]["language"] == ""
    assert "language_code" not in update_params


@pytest.mark.asyncio
async def test_save_meme_description_normalizes_known_string_language(monkeypatch):
    fetch_one = AsyncMock(return_value={})
    monkeypatch.setattr(repository, "fetch_one", fetch_one)

    await repository.save_meme_description(
        42,
        {},
        {
            "ocr_text": "visible text",
            "description": "a meme",
            "language": " RU ",
            "__model": "test-model:free",
        },
    )

    update_query = fetch_one.await_args.args[0]
    update_params = update_query.compile(dialect=postgresql.dialect()).params

    assert update_params["language_code"] == "ru"
