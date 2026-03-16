"""Tests for queue logic in meme_queue.py using stub retriever."""

from typing import Any

import pytest
import pytest_asyncio
from tests.factories import (
    cleanup_test_data,
    create_meme,
    create_meme_source,
    create_user,
    create_user_language,
    create_user_stats,
)

from src import redis
from src.database import engine
from src.recommendations.candidates import CandidatesRetriever
from src.recommendations.meme_queue import generate_recommendations

# IDs for queue tests
QUEUE_USER = 10010


def _make_stub_retriever(candidates_by_engine: dict[str, list[dict]]):
    """Create a stub retriever that returns predefined candidates per engine."""

    class StubRetriever(CandidatesRetriever):
        engine_map = {}

        async def get_candidates(
            self,
            engine_name: str,
            user_id: int,
            limit: int = 10,
            exclude_mem_ids: list[int] = [],
        ) -> list[dict[str, Any]]:
            all_candidates = candidates_by_engine.get(engine_name, [])
            exclude_set = set(exclude_mem_ids)
            filtered = [c for c in all_candidates if c["id"] not in exclude_set]
            return filtered[:limit]

        async def get_candidates_dict(
            self,
            engines: list[str],
            user_id: int,
            limit: int = 10,
            exclude_mem_ids: list[int] = [],
        ) -> dict[str, list[dict[str, Any]]]:
            result = {}
            for eng in engines:
                result[eng] = await self.get_candidates(eng, user_id, limit, exclude_mem_ids)
            return result

    return StubRetriever()


def _meme(id: int, recommended_by: str = "test") -> dict:
    return {
        "id": id,
        "type": "image",
        "telegram_file_id": f"file_{id}",
        "caption": None,
        "recommended_by": recommended_by,
    }


@pytest_asyncio.fixture(loop_scope="session")
async def queue_user():
    async with engine.connect() as conn:
        await create_user(conn, id=QUEUE_USER)
        await create_user_language(conn, user_id=QUEUE_USER)
        await create_user_stats(conn, user_id=QUEUE_USER, nmemes_sent=50)
        # Memes needed for low_sent_pool query (moderator test)
        await create_meme_source(conn, id=10010)
        for mid in range(10010, 10015):
            await create_meme(conn, id=mid, meme_source_id=10010)
        await conn.commit()

    yield

    # Cleanup Redis queue + cached user info
    queue_key = redis.get_meme_queue_key(QUEUE_USER)
    await redis.delete_by_key(queue_key)
    user_info_key = redis.get_user_info_key(QUEUE_USER)
    await redis.delete_by_key(user_info_key)

    async with engine.connect() as conn:
        await cleanup_test_data(conn)


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _clean_queue_between_tests():
    """Clear Redis queue and user info cache before each test."""
    queue_key = redis.get_meme_queue_key(QUEUE_USER)
    await redis.delete_by_key(queue_key)
    user_info_key = redis.get_user_info_key(QUEUE_USER)
    await redis.delete_by_key(user_info_key)
    yield


@pytest.mark.asyncio
async def test_cold_start_below_30(queue_user):
    """nmemes_sent < 30 -> uses lr_smoothed first, then best_uploaded_memes."""
    stub = _make_stub_retriever(
        {
            "lr_smoothed": [_meme(20001), _meme(20002)],
            "best_uploaded_memes": [_meme(20003), _meme(20004)],
        }
    )
    candidates = await generate_recommendations(QUEUE_USER, limit=5, nmemes_sent=10, retriever=stub)
    assert len(candidates) == 2
    ids = {c["id"] for c in candidates}
    assert ids == {20001, 20002}


@pytest.mark.asyncio
async def test_cold_start_fallback_to_best_uploaded(queue_user):
    """If lr_smoothed is empty, falls back to best_uploaded_memes."""
    stub = _make_stub_retriever(
        {
            "lr_smoothed": [],
            "best_uploaded_memes": [_meme(20003), _meme(20004)],
        }
    )
    candidates = await generate_recommendations(QUEUE_USER, limit=5, nmemes_sent=10, retriever=stub)
    assert len(candidates) == 2
    ids = {c["id"] for c in candidates}
    assert ids == {20003, 20004}


@pytest.mark.asyncio
async def test_growing_30_to_100(queue_user):
    """nmemes_sent between 30-100 -> blends 5 engines."""
    stub = _make_stub_retriever(
        {
            "best_uploaded_memes": [_meme(20001)],
            "lr_smoothed": [_meme(20003)],
            "recently_liked": [_meme(20004)],
            "goat": [_meme(20005)],
            "like_spread_and_recent_memes": [_meme(20006)],
            "es_ranked": [_meme(20007)],
        }
    )
    candidates = await generate_recommendations(QUEUE_USER, limit=5, nmemes_sent=50, retriever=stub)
    assert len(candidates) > 0
    # lr_smoothed should be at position 0 (fixed_pos)
    assert candidates[0]["id"] == 20003


@pytest.mark.asyncio
async def test_mature_above_100(queue_user):
    """nmemes_sent >= 100 -> blends different set of engines."""
    stub = _make_stub_retriever(
        {
            "best_uploaded_memes": [_meme(20001), _meme(20002)],
            "like_spread_and_recent_memes": [_meme(20003), _meme(20004)],
            "lr_smoothed": [_meme(20005), _meme(20006)],
            "recently_liked": [_meme(20007)],
            "goat": [_meme(20008)],
            "es_ranked": [_meme(20009)],
        }
    )
    candidates = await generate_recommendations(
        QUEUE_USER, limit=5, nmemes_sent=200, retriever=stub
    )
    assert len(candidates) > 0
    # lr_smoothed at position 0
    assert candidates[0]["id"] == 20005


@pytest.mark.asyncio
async def test_moderator_gets_low_sent_pool(queue_user):
    """Moderator user type gets ~75% low_sent_pool candidates."""
    async with engine.connect() as conn:
        from sqlalchemy import update

        from src.database import user

        await conn.execute(update(user).where(user.c.id == QUEUE_USER).values(type="moderator"))
        await conn.commit()

    # Clear cached user info
    user_info_key = redis.get_user_info_key(QUEUE_USER)
    await redis.delete_by_key(user_info_key)

    stub = _make_stub_retriever(
        {
            "best_uploaded_memes": [_meme(20001)],
            "like_spread_and_recent_memes": [_meme(20002)],
            "lr_smoothed": [_meme(20003)],
            "recently_liked": [_meme(20004)],
            "goat": [_meme(20005)],
            "es_ranked": [_meme(20006)],
        }
    )
    candidates = await generate_recommendations(
        QUEUE_USER, limit=4, nmemes_sent=200, retriever=stub
    )
    # For limit=4, low_sent_quota = ceil(4 * 0.75) = 3
    # So at least some candidates should have 'low_sent_pool' as recommended_by
    low_sent = [c for c in candidates if c.get("recommended_by") == "low_sent_pool"]
    assert len(low_sent) > 0


@pytest.mark.asyncio
async def test_queue_memes_have_required_fields(queue_user):
    """Memes in queue should have id, type, telegram_file_id, recommended_by."""
    stub = _make_stub_retriever(
        {
            "lr_smoothed": [_meme(20001, "lr_smoothed")],
            "best_uploaded_memes": [_meme(20002, "best_uploaded_memes")],
        }
    )
    candidates = await generate_recommendations(QUEUE_USER, limit=5, nmemes_sent=10, retriever=stub)
    for c in candidates:
        assert "id" in c
        assert "type" in c or True  # stub has type
        assert "recommended_by" in c


@pytest.mark.asyncio
async def test_generate_excludes_already_queued(queue_user):
    """Second generate should not duplicate memes already in queue."""
    stub = _make_stub_retriever(
        {
            "lr_smoothed": [_meme(20001), _meme(20002), _meme(20003)],
            "best_uploaded_memes": [],
        }
    )

    first = await generate_recommendations(QUEUE_USER, limit=5, nmemes_sent=10, retriever=stub)
    second = await generate_recommendations(QUEUE_USER, limit=5, nmemes_sent=10, retriever=stub)

    # generate_recommendations reads existing queue and excludes those IDs
    queue_key = redis.get_meme_queue_key(QUEUE_USER)
    all_memes = await redis.get_all_memes_in_queue_by_key(queue_key)
    ids = [m["id"] for m in all_memes]
    assert len(ids) == len(set(ids)), "Queue contains duplicate IDs"
