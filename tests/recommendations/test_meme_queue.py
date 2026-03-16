from typing import Any

import pytest

from sqlalchemy.dialects.postgresql import insert

from src.database import engine, user, user_language
from src.recommendations.candidates import CandidatesRetriever
from src.recommendations.meme_queue import generate_recommendations

TEST_USER_ID = 99999


@pytest.fixture(autouse=True, scope="module")
async def setup_test_user():
    async with engine.begin() as conn:
        await conn.execute(
            insert(user).values(id=TEST_USER_ID, type="user").on_conflict_do_nothing()
        )
        await conn.execute(
            insert(user_language)
            .values(user_id=TEST_USER_ID, language_code="en")
            .on_conflict_do_nothing()
        )


@pytest.mark.asyncio
async def test_generate_below_30():
    """Cold start (<30 memes): uses lr_smoothed, falls back to best_uploaded_memes"""

    async def get_lr_smoothed(
        self,
        user_id: int,
        limit: int = 10,
        exclude_meme_ids: list[int] = [],
    ) -> list[dict[str, Any]]:
        return [
            {"id": 1},
            {"id": 2},
        ]

    async def get_lr_smoothed_empty(
        self,
        user_id: int,
        limit: int = 10,
        exclude_meme_ids: list[int] = [],
    ) -> list[dict[str, Any]]:
        return []

    async def best_uploaded_memes(
        self,
        user_id: int,
        limit: int = 10,
        exclude_meme_ids: list[int] = [],
    ) -> list[dict[str, Any]]:
        return [
            {"id": 3},
            {"id": 4},
        ]

    # lr_smoothed has candidates → use them
    class TestRetriever(CandidatesRetriever):
        engine_map = {
            "lr_smoothed": get_lr_smoothed,
            "best_uploaded_memes": best_uploaded_memes,
        }

    candidates = await generate_recommendations(TEST_USER_ID, 10, 10, TestRetriever())
    assert len(candidates) == 2
    assert candidates[0]["id"] in [1, 2]
    assert candidates[1]["id"] in [1, 2]

    # lr_smoothed empty → fallback to best_uploaded_memes
    class TestRetriever(CandidatesRetriever):
        engine_map = {
            "lr_smoothed": get_lr_smoothed_empty,
            "best_uploaded_memes": best_uploaded_memes,
        }

    candidates = await generate_recommendations(TEST_USER_ID, 10, 10, TestRetriever())
    assert len(candidates) == 2
    assert candidates[0]["id"] in [3, 4]
    assert candidates[1]["id"] in [3, 4]


@pytest.mark.asyncio
async def test_generate_below_100():
    """Growing users (30-100): blended from lr_smoothed, recently_liked, goat,
    like_spread_and_recent_memes, best_uploaded_memes. lr_smoothed pinned at pos 0."""

    async def best_uploaded_memes(
        self,
        user_id: int,
        limit: int = 10,
        exclude_meme_ids: list[int] = [],
    ) -> list[dict[str, Any]]:
        return [
            {"id": 1},
            {"id": 2},
        ]

    async def like_spread_and_recent_memes(
        self,
        user_id: int,
        limit: int = 10,
        exclude_meme_ids: list[int] = [],
    ) -> list[dict[str, Any]]:
        return [
            {"id": 3},
            {"id": 4},
        ]

    async def get_lr_smoothed(
        self,
        user_id: int,
        limit: int = 10,
        exclude_meme_ids: list[int] = [],
    ) -> list[dict[str, Any]]:
        return [
            {"id": 7},
            {"id": 8},
        ]

    async def get_recently_liked(
        self,
        user_id: int,
        limit: int = 10,
        exclude_meme_ids: list[int] = [],
    ) -> list[dict[str, Any]]:
        return [
            {"id": 9},
            {"id": 10},
        ]

    async def goat(
        self,
        user_id: int,
        limit: int = 10,
        exclude_meme_ids: list[int] = [],
    ) -> list[dict[str, Any]]:
        return [
            {"id": 11},
            {"id": 12},
        ]

    async def es_ranked(
        self,
        user_id: int,
        limit: int = 10,
        exclude_meme_ids: list[int] = [],
    ) -> list[dict[str, Any]]:
        return [
            {"id": 13},
            {"id": 14},
        ]

    class TestRetriever(CandidatesRetriever):
        engine_map = {
            "best_uploaded_memes": best_uploaded_memes,
            "like_spread_and_recent_memes": like_spread_and_recent_memes,
            "lr_smoothed": get_lr_smoothed,
            "recently_liked": get_recently_liked,
            "goat": goat,
            "es_ranked": es_ranked,
        }

    candidates = await generate_recommendations(TEST_USER_ID, 10, 40, TestRetriever())
    assert len(candidates) == 10
    # lr_smoothed is pinned at position 0
    assert candidates[0]["id"] in [7, 8]


@pytest.mark.asyncio
async def test_generate_above_100():
    async def best_uploaded_memes(
        self,
        user_id: int,
        limit: int = 10,
        exclude_meme_ids: list[int] = [],
    ) -> list[dict[str, Any]]:
        return [
            {"id": 1},
            {"id": 2},
            {"id": 3},
        ]

    async def like_spread_and_recent_memes(
        self,
        user_id: int,
        limit: int = 10,
        exclude_meme_ids: list[int] = [],
    ) -> list[dict[str, Any]]:
        return [
            {"id": 4},
            {"id": 5},
            {"id": 6},
        ]

    async def get_lr_smoothed(
        self,
        user_id: int,
        limit: int = 10,
        exclude_meme_ids: list[int] = [],
    ) -> list[dict[str, Any]]:
        return [
            {"id": 7},
            {"id": 8},
            {"id": 9},
            {"id": 10},
        ]

    async def get_recently_liked(
        self,
        user_id: int,
        limit: int = 10,
        exclude_meme_ids: list[int] = [],
    ) -> list[dict[str, Any]]:
        return [
            {"id": 11},
            {"id": 12},
        ]

    async def goat(
        self,
        user_id: int,
        limit: int = 10,
        exclude_meme_ids: list[int] = [],
    ) -> list[dict[str, Any]]:
        return [
            {"id": 13},
            {"id": 14},
        ]

    async def es_ranked(
        self,
        user_id: int,
        limit: int = 10,
        exclude_meme_ids: list[int] = [],
    ) -> list[dict[str, Any]]:
        return [
            {"id": 15},
            {"id": 16},
        ]

    class TestRetriever(CandidatesRetriever):
        engine_map = {
            "best_uploaded_memes": best_uploaded_memes,
            "like_spread_and_recent_memes": like_spread_and_recent_memes,
            "lr_smoothed": get_lr_smoothed,
            "recently_liked": get_recently_liked,
            "goat": goat,
            "es_ranked": es_ranked,
        }

    candidates = await generate_recommendations(TEST_USER_ID, 10, 200, TestRetriever(), random_seed=102)
    assert len(candidates) == 10
    # lr_smoothed is pinned at position 0
    assert candidates[0]["id"] in [7, 8, 9, 10]


@pytest.mark.asyncio
async def test_generate_empty_above_100():
    async def best_uploaded_memes(
        self,
        user_id: int,
        limit: int = 10,
        exclude_meme_ids: list[int] = [],
    ) -> list[dict[str, Any]]:
        return []

    async def like_spread_and_recent_memes(
        self,
        user_id: int,
        limit: int = 10,
        exclude_meme_ids: list[int] = [],
    ) -> list[dict[str, Any]]:
        return []

    async def get_lr_smoothed(
        self,
        user_id: int,
        limit: int = 10,
        exclude_meme_ids: list[int] = [],
    ) -> list[dict[str, Any]]:
        return []

    async def get_recently_liked(
        self,
        user_id: int,
        limit: int = 10,
        exclude_meme_ids: list[int] = [],
    ) -> list[dict[str, Any]]:
        return []

    async def goat(
        self,
        user_id: int,
        limit: int = 10,
        exclude_meme_ids: list[int] = [],
    ) -> list[dict[str, Any]]:
        return []

    async def es_ranked(
        self,
        user_id: int,
        limit: int = 10,
        exclude_meme_ids: list[int] = [],
    ) -> list[dict[str, Any]]:
        return []

    class TestRetriever(CandidatesRetriever):
        engine_map = {
            "best_uploaded_memes": best_uploaded_memes,
            "like_spread_and_recent_memes": like_spread_and_recent_memes,
            "lr_smoothed": get_lr_smoothed,
            "recently_liked": get_recently_liked,
            "goat": goat,
            "es_ranked": es_ranked,
        }

    # All engines empty → empty result
    candidates = await generate_recommendations(TEST_USER_ID, 10, 200, TestRetriever())
    assert len(candidates) == 0

    # Same for high meme count — no fallback engine anymore
    candidates = await generate_recommendations(TEST_USER_ID, 10, 1200, TestRetriever())
    assert len(candidates) == 0
