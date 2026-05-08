from collections import defaultdict
from unittest.mock import AsyncMock, patch

import pytest

from src.recommendations.candidates import CandidatesRetriever
from src.recommendations.meme_queue import (
    MATURE_BLENDER_CONTROL_WEIGHTS,
    MATURE_BLENDER_TREATMENT_WEIGHTS,
    RECENTLY_LIKED_BLENDER_CONTROL,
    RECENTLY_LIKED_BLENDER_EXPERIMENT_ID,
    RECENTLY_LIKED_BLENDER_TREATMENT,
    generate_recommendations,
    get_or_assign_recently_liked_blender_variant,
    get_recently_liked_blender_weights,
)

TEST_USER_ID = 99999


@pytest.fixture(autouse=True)
def mock_redis():
    """Mock Redis and user_info calls — these tests validate blending logic, not Redis."""
    user_info = defaultdict(int, {"nmemes_sent": 0})
    with (
        patch(
            "src.recommendations.meme_queue.get_user_info",
            new_callable=AsyncMock,
            return_value=user_info,
        ),
        patch(
            "src.recommendations.meme_queue.redis.get_all_memes_in_queue_by_key",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.recommendations.meme_queue.redis.add_memes_to_queue_by_key",
            new_callable=AsyncMock,
        ),
    ):
        yield


# ── Cold start Phase 1 (nmemes_sent < 6): cold_start_explore ──


@pytest.mark.asyncio
async def test_cold_start_phase1_uses_explore():
    """Phase 1 (<6 memes): uses cold_start_explore engine"""

    async def cold_start_explore(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 101}, {"id": 102}, {"id": 103}]

    async def cold_start_adapt(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 201}]

    async def lr_smoothed(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 301}]

    async def best_uploaded(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 401}]

    class TestRetriever(CandidatesRetriever):
        engine_map = {
            "cold_start_explore": cold_start_explore,
            "cold_start_adapt": cold_start_adapt,
            "lr_smoothed": lr_smoothed,
            "best_uploaded_memes": best_uploaded,
        }

    candidates = await generate_recommendations(
        TEST_USER_ID, 10, nmemes_sent=3, retriever=TestRetriever()
    )
    assert len(candidates) == 3
    assert candidates[0]["id"] == 101


@pytest.mark.asyncio
async def test_cold_start_phase1_fallback_to_lr_smoothed():
    """Phase 1 empty → fallback to lr_smoothed"""

    async def empty(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return []

    async def lr_smoothed(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 301}, {"id": 302}]

    async def best_uploaded(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 401}]

    class TestRetriever(CandidatesRetriever):
        engine_map = {
            "cold_start_explore": empty,
            "cold_start_adapt": empty,
            "lr_smoothed": lr_smoothed,
            "best_uploaded_memes": best_uploaded,
        }

    candidates = await generate_recommendations(
        TEST_USER_ID, 10, nmemes_sent=0, retriever=TestRetriever()
    )
    assert len(candidates) == 2
    assert candidates[0]["id"] in [301, 302]


@pytest.mark.asyncio
async def test_cold_start_phase1_fallback_to_uploaded():
    """Phase 1 + lr_smoothed both empty → fallback to best_uploaded_memes"""

    async def empty(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return []

    async def best_uploaded(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 401}]

    class TestRetriever(CandidatesRetriever):
        engine_map = {
            "cold_start_explore": empty,
            "cold_start_adapt": empty,
            "lr_smoothed": empty,
            "best_uploaded_memes": best_uploaded,
        }

    candidates = await generate_recommendations(
        TEST_USER_ID, 10, nmemes_sent=2, retriever=TestRetriever()
    )
    assert len(candidates) == 1
    assert candidates[0]["id"] == 401


# ── Cold start Phase 2 (6 <= nmemes_sent < 16): cold_start_adapt ──


@pytest.mark.asyncio
async def test_cold_start_phase2_uses_adapt():
    """Phase 2 (6-15 memes): uses cold_start_adapt engine"""

    async def cold_start_explore(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 101}]

    async def cold_start_adapt(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 201}, {"id": 202}, {"id": 203}]

    async def lr_smoothed(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 301}]

    async def best_uploaded(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 401}]

    class TestRetriever(CandidatesRetriever):
        engine_map = {
            "cold_start_explore": cold_start_explore,
            "cold_start_adapt": cold_start_adapt,
            "lr_smoothed": lr_smoothed,
            "best_uploaded_memes": best_uploaded,
        }

    candidates = await generate_recommendations(
        TEST_USER_ID, 10, nmemes_sent=8, retriever=TestRetriever()
    )
    assert len(candidates) == 3
    assert candidates[0]["id"] == 201


@pytest.mark.asyncio
async def test_cold_start_phase2_fallback():
    """Phase 2 empty → fallback to lr_smoothed"""

    async def empty(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return []

    async def lr_smoothed(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 301}]

    async def best_uploaded(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 401}]

    class TestRetriever(CandidatesRetriever):
        engine_map = {
            "cold_start_explore": empty,
            "cold_start_adapt": empty,
            "lr_smoothed": lr_smoothed,
            "best_uploaded_memes": best_uploaded,
        }

    candidates = await generate_recommendations(
        TEST_USER_ID, 10, nmemes_sent=10, retriever=TestRetriever()
    )
    assert len(candidates) == 1
    assert candidates[0]["id"] == 301


# ── Cold start Phase 3 (16 <= nmemes_sent < 30): transition blend ──


@pytest.mark.asyncio
async def test_cold_start_phase3_blends():
    """Phase 3 (16-30 memes): blends cold_start_adapt + growing engines"""

    async def cold_start_adapt(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 201}, {"id": 202}, {"id": 203}]

    async def lr_smoothed(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 301}, {"id": 302}]

    async def like_spread(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 501}, {"id": 502}]

    async def best_uploaded(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 401}]

    class TestRetriever(CandidatesRetriever):
        engine_map = {
            "cold_start_adapt": cold_start_adapt,
            "lr_smoothed": lr_smoothed,
            "like_spread_and_recent_memes": like_spread,
            "best_uploaded_memes": best_uploaded,
            "cold_start_explore": cold_start_adapt,  # unused but needed in map
        }

    candidates = await generate_recommendations(
        TEST_USER_ID, 7, nmemes_sent=20, retriever=TestRetriever(), random_seed=42
    )
    assert len(candidates) == 7
    # cold_start_adapt is pinned at position 0
    assert candidates[0]["id"] in [201, 202, 203]


# ── Growing (30-100) and Mature (100+) — existing behavior ──


@pytest.mark.asyncio
async def test_generate_below_100():
    """Growing users (30-100): blended from multiple engines. lr_smoothed pinned at pos 0."""

    async def best_uploaded_memes(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 1}, {"id": 2}]

    async def like_spread_and_recent_memes(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 3}, {"id": 4}]

    async def get_lr_smoothed(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 7}, {"id": 8}]

    async def get_recently_liked(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 9}, {"id": 10}]

    async def goat(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 11}, {"id": 12}]

    async def es_ranked(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 13}, {"id": 14}]

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
    async def best_uploaded_memes(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 1}, {"id": 2}, {"id": 3}]

    async def like_spread_and_recent_memes(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 4}, {"id": 5}, {"id": 6}]

    async def get_lr_smoothed(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 7}, {"id": 8}, {"id": 9}, {"id": 10}]

    async def get_recently_liked(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 11}, {"id": 12}]

    async def goat(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 13}, {"id": 14}]

    async def es_ranked(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 15}, {"id": 16}]

    class TestRetriever(CandidatesRetriever):
        engine_map = {
            "best_uploaded_memes": best_uploaded_memes,
            "like_spread_and_recent_memes": like_spread_and_recent_memes,
            "lr_smoothed": get_lr_smoothed,
            "recently_liked": get_recently_liked,
            "goat": goat,
            "es_ranked": es_ranked,
        }

    with patch(
        "src.recommendations.meme_queue.get_or_assign_recently_liked_blender_variant",
        new_callable=AsyncMock,
        return_value=RECENTLY_LIKED_BLENDER_CONTROL,
    ):
        candidates = await generate_recommendations(
            TEST_USER_ID, 10, 200, TestRetriever(), random_seed=102
        )
    assert len(candidates) == 10
    # lr_smoothed is pinned at position 0
    assert candidates[0]["id"] in [7, 8, 9, 10]


@pytest.mark.asyncio
async def test_generate_above_100_treatment_uses_recently_liked_weights():
    captured_weights = None

    async def best_uploaded_memes(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 1}]

    async def like_spread_and_recent_memes(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 2}]

    async def get_lr_smoothed(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 3}]

    async def get_recently_liked(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 4}]

    async def goat(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 5}]

    async def es_ranked(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 6}]

    def capture_blend(candidates_dict, weights_dict, fixed_pos=None, limit=0, random_seed=None):
        nonlocal captured_weights
        captured_weights = weights_dict
        return [{"id": 4, "recommended_by": "recently_liked"}]

    class TestRetriever(CandidatesRetriever):
        engine_map = {
            "best_uploaded_memes": best_uploaded_memes,
            "like_spread_and_recent_memes": like_spread_and_recent_memes,
            "lr_smoothed": get_lr_smoothed,
            "recently_liked": get_recently_liked,
            "goat": goat,
            "es_ranked": es_ranked,
        }

    with (
        patch(
            "src.recommendations.meme_queue.get_or_assign_recently_liked_blender_variant",
            new_callable=AsyncMock,
            return_value=RECENTLY_LIKED_BLENDER_TREATMENT,
        ) as assign_variant,
        patch("src.recommendations.meme_queue.blend", side_effect=capture_blend),
    ):
        candidates = await generate_recommendations(
            TEST_USER_ID, 10, 200, TestRetriever(), random_seed=102
        )

    assert candidates == [{"id": 4, "recommended_by": "recently_liked"}]
    assert captured_weights == MATURE_BLENDER_TREATMENT_WEIGHTS
    assign_variant.assert_awaited_once_with(TEST_USER_ID)


@pytest.mark.asyncio
async def test_recently_liked_blender_assignment_is_mature_only():
    async def empty(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return []

    class TestRetriever(CandidatesRetriever):
        engine_map = {
            "best_uploaded_memes": empty,
            "like_spread_and_recent_memes": empty,
            "lr_smoothed": empty,
            "recently_liked": empty,
            "goat": empty,
            "es_ranked": empty,
            "cold_start_explore": empty,
            "cold_start_adapt": empty,
        }

    with patch(
        "src.recommendations.meme_queue.get_or_assign_recently_liked_blender_variant",
        new_callable=AsyncMock,
        return_value=RECENTLY_LIKED_BLENDER_TREATMENT,
    ) as assign_variant:
        await generate_recommendations(TEST_USER_ID, 10, 29, TestRetriever())
        await generate_recommendations(TEST_USER_ID, 10, 99, TestRetriever())

    assign_variant.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_recently_liked_blender_assignment_wins():
    with patch(
        "src.recommendations.meme_queue.get_experiment_variant",
        new_callable=AsyncMock,
        return_value=RECENTLY_LIKED_BLENDER_TREATMENT,
    ) as get_variant:
        variant = await get_or_assign_recently_liked_blender_variant(101)

    assert variant == RECENTLY_LIKED_BLENDER_TREATMENT
    get_variant.assert_awaited_once_with(101, RECENTLY_LIKED_BLENDER_EXPERIMENT_ID)


@pytest.mark.asyncio
async def test_recently_liked_blender_even_user_gets_treatment():
    with (
        patch(
            "src.recommendations.meme_queue.get_experiment_variant",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.recommendations.meme_queue.assign_experiment",
            new_callable=AsyncMock,
            return_value=True,
        ) as assign,
    ):
        variant = await get_or_assign_recently_liked_blender_variant(100)

    assert variant == RECENTLY_LIKED_BLENDER_TREATMENT
    assign.assert_awaited_once_with(
        100,
        RECENTLY_LIKED_BLENDER_EXPERIMENT_ID,
        RECENTLY_LIKED_BLENDER_TREATMENT,
    )


@pytest.mark.asyncio
async def test_recently_liked_blender_odd_user_gets_control():
    with (
        patch(
            "src.recommendations.meme_queue.get_experiment_variant",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.recommendations.meme_queue.assign_experiment",
            new_callable=AsyncMock,
            return_value=True,
        ) as assign,
    ):
        variant = await get_or_assign_recently_liked_blender_variant(101)

    assert variant == RECENTLY_LIKED_BLENDER_CONTROL
    assign.assert_awaited_once_with(
        101,
        RECENTLY_LIKED_BLENDER_EXPERIMENT_ID,
        RECENTLY_LIKED_BLENDER_CONTROL,
    )


@pytest.mark.asyncio
async def test_recently_liked_blender_race_rereads_winning_assignment():
    with (
        patch(
            "src.recommendations.meme_queue.get_experiment_variant",
            new_callable=AsyncMock,
            side_effect=[None, RECENTLY_LIKED_BLENDER_CONTROL],
        ),
        patch(
            "src.recommendations.meme_queue.assign_experiment",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        variant = await get_or_assign_recently_liked_blender_variant(100)

    assert variant == RECENTLY_LIKED_BLENDER_CONTROL


@pytest.mark.asyncio
async def test_recently_liked_blender_weights_fall_back_to_control_on_assignment_error():
    with patch(
        "src.recommendations.meme_queue.get_or_assign_recently_liked_blender_variant",
        new_callable=AsyncMock,
        side_effect=RuntimeError("assignment unavailable"),
    ):
        weights = await get_recently_liked_blender_weights(100)

    assert weights == MATURE_BLENDER_CONTROL_WEIGHTS


@pytest.mark.asyncio
async def test_recently_liked_blender_treatment_increases_recently_liked_weight():
    with patch(
        "src.recommendations.meme_queue.get_or_assign_recently_liked_blender_variant",
        new_callable=AsyncMock,
        return_value=RECENTLY_LIKED_BLENDER_TREATMENT,
    ):
        weights = await get_recently_liked_blender_weights(100)

    assert weights == MATURE_BLENDER_TREATMENT_WEIGHTS
    assert weights["recently_liked"] > MATURE_BLENDER_CONTROL_WEIGHTS["recently_liked"]
    assert weights["lr_smoothed"] < MATURE_BLENDER_CONTROL_WEIGHTS["lr_smoothed"]


@pytest.mark.asyncio
async def test_generate_empty_above_100():
    async def empty(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return []

    class TestRetriever(CandidatesRetriever):
        engine_map = {
            "best_uploaded_memes": empty,
            "like_spread_and_recent_memes": empty,
            "lr_smoothed": empty,
            "recently_liked": empty,
            "goat": empty,
            "es_ranked": empty,
        }

    with patch(
        "src.recommendations.meme_queue.get_or_assign_recently_liked_blender_variant",
        new_callable=AsyncMock,
        return_value=RECENTLY_LIKED_BLENDER_CONTROL,
    ):
        # All engines empty → empty result
        candidates = await generate_recommendations(TEST_USER_ID, 10, 200, TestRetriever())
        assert len(candidates) == 0

        # Same for high meme count — no fallback engine anymore
        candidates = await generate_recommendations(TEST_USER_ID, 10, 1200, TestRetriever())
    assert len(candidates) == 0


# ── All phases empty → empty result ──


@pytest.mark.asyncio
async def test_cold_start_all_empty():
    """If all engines return empty during cold start, result is empty (no crash)"""

    async def empty(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return []

    class TestRetriever(CandidatesRetriever):
        engine_map = {
            "cold_start_explore": empty,
            "cold_start_adapt": empty,
            "lr_smoothed": empty,
            "best_uploaded_memes": empty,
            "like_spread_and_recent_memes": empty,
        }

    for nmemes in [0, 3, 8, 12, 20, 25]:
        candidates = await generate_recommendations(TEST_USER_ID, 10, nmemes, TestRetriever())
        assert len(candidates) == 0, f"Expected empty at nmemes_sent={nmemes}"
