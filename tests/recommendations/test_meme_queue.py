from collections import defaultdict
from unittest.mock import AsyncMock, patch

import pytest

from src.recommendations.blender_experiments import (
    MATURE_BLENDER_CONTROL_WEIGHTS,
    MATURE_BLENDER_TREATMENT_WEIGHTS,
)
from src.recommendations.candidates import CandidatesRetriever
from src.recommendations.meme_queue import (
    _cold_start_allowed_by_realtime_state,
    generate_recommendations,
    get_next_meme_for_user,
)

TEST_USER_ID = 99999


def _patch_user_info(nsessions: int = 0, nmemes_sent: int = 0, **extra):
    user_info = defaultdict(int, {"nmemes_sent": nmemes_sent, "nsessions": nsessions, **extra})
    return patch(
        "src.recommendations.meme_queue.get_user_info",
        new_callable=AsyncMock,
        return_value=user_info,
    )


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
        patch(
            "src.recommendations.meme_queue.get_text_light_blender_v1_weights",
            new_callable=AsyncMock,
            side_effect=lambda user_id, weights: weights,
        ),
        patch(
            "src.recommendations.meme_queue._get_realtime_cold_start_routing_state",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        yield


# ── Cold start Phase 1 (nmemes_sent < 6): cold_start_explore ──


@pytest.mark.parametrize(
    ("state", "allowed"),
    [
        (
            {
                "prior_sent_count": 26,
                "nsessions_after_next_send": 1,
                "cold_start_account_too_old": False,
            },
            True,
        ),
        (
            {
                "prior_sent_count": 26,
                "nsessions_after_next_send": 2,
                "cold_start_account_too_old": False,
            },
            False,
        ),
        (
            {
                "prior_sent_count": 30,
                "nsessions_after_next_send": 1,
                "cold_start_account_too_old": False,
            },
            False,
        ),
        (
            {
                "prior_sent_count": 8,
                "nsessions_after_next_send": 1,
                "cold_start_account_too_old": True,
            },
            False,
        ),
    ],
)
def test_cold_start_realtime_state_predicate(state, allowed):
    assert _cold_start_allowed_by_realtime_state(state) is allowed


@pytest.mark.asyncio
async def test_get_next_meme_for_user_skips_stale_queue_payloads():
    queued_payloads = [
        {
            "id": 101,
            "type": "image",
            "telegram_file_id": "stale-file-id",
            "caption": None,
        },
        {
            "id": 102,
            "type": "image",
            "telegram_file_id": "fresh-file-id",
            "caption": None,
        },
    ]

    async def pop_queue(_queue_key):
        return queued_payloads.pop(0) if queued_payloads else None

    async def is_sendable(_user_id: int, meme_id: int, _recommended_by: str | None = None) -> bool:
        return meme_id == 102

    with (
        patch(
            "src.recommendations.meme_queue.redis.pop_meme_from_queue_by_key",
            new_callable=AsyncMock,
            side_effect=pop_queue,
        ),
        patch(
            "src.recommendations.meme_queue._queued_meme_is_sendable",
            new_callable=AsyncMock,
            side_effect=is_sendable,
        ),
    ):
        meme = await get_next_meme_for_user(TEST_USER_ID)

    assert meme is not None
    assert meme.id == 102


@pytest.mark.asyncio
async def test_get_next_meme_for_user_refills_after_draining_stale_payloads():
    queued_payloads = [
        {
            "id": 101,
            "type": "image",
            "telegram_file_id": "stale-file-id",
            "caption": None,
        },
    ]

    async def pop_queue(_queue_key):
        return queued_payloads.pop(0) if queued_payloads else None

    async def refill_queue(_user_id: int) -> bool:
        queued_payloads.append(
            {
                "id": 102,
                "type": "image",
                "telegram_file_id": "fresh-file-id",
                "caption": None,
            }
        )
        return True

    async def is_sendable(_user_id: int, meme_id: int, _recommended_by: str | None = None) -> bool:
        return meme_id == 102

    with (
        patch(
            "src.recommendations.meme_queue.redis.pop_meme_from_queue_by_key",
            new_callable=AsyncMock,
            side_effect=pop_queue,
        ),
        patch(
            "src.recommendations.meme_queue._queued_meme_is_sendable",
            new_callable=AsyncMock,
            side_effect=is_sendable,
        ),
        patch(
            "src.recommendations.meme_queue.check_queue",
            new_callable=AsyncMock,
            side_effect=refill_queue,
        ) as check_queue,
    ):
        meme = await get_next_meme_for_user(TEST_USER_ID)

    assert meme is not None
    assert meme.id == 102
    check_queue.assert_awaited_once_with(TEST_USER_ID)


@pytest.mark.asyncio
async def test_get_next_meme_for_user_discards_cold_start_payload_when_realtime_guard_blocks():
    queued_payloads = [
        {
            "id": 101,
            "type": "image",
            "telegram_file_id": "stale-cold-start-file-id",
            "caption": None,
            "recommended_by": "cold_start_adapt",
        },
        {
            "id": 102,
            "type": "image",
            "telegram_file_id": "growing-file-id",
            "caption": None,
            "recommended_by": "lr_smoothed",
        },
    ]
    ineligible_state = {
        "account_age_days": 28,
        "cold_start_account_too_old": False,
        "prior_sent_count": 26,
        "nsessions_after_next_send": 2,
    }

    async def pop_queue(_queue_key):
        return queued_payloads.pop(0) if queued_payloads else None

    with (
        patch(
            "src.recommendations.meme_queue.redis.pop_meme_from_queue_by_key",
            new_callable=AsyncMock,
            side_effect=pop_queue,
        ),
        patch(
            "src.recommendations.meme_queue.fetch_one",
            new_callable=AsyncMock,
            side_effect=[{"id": 101}, {"id": 102}],
        ),
        patch(
            "src.recommendations.meme_queue._get_realtime_cold_start_routing_state",
            new_callable=AsyncMock,
            return_value=ineligible_state,
        ) as realtime_state,
    ):
        meme = await get_next_meme_for_user(TEST_USER_ID)

    assert meme is not None
    assert meme.id == 102
    realtime_state.assert_awaited_once_with(TEST_USER_ID)


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
async def test_cold_start_phase1_fallback_to_text_light_lr_smoothed():
    """Phase 1 empty → fallback to text_light_lr_smoothed"""

    async def empty(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return []

    async def text_light_lr_smoothed(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 301}, {"id": 302}]

    async def best_uploaded(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 401}]

    class TestRetriever(CandidatesRetriever):
        engine_map = {
            "cold_start_explore": empty,
            "cold_start_adapt": empty,
            "text_light_lr_smoothed": text_light_lr_smoothed,
            "best_uploaded_memes": best_uploaded,
        }

    candidates = await generate_recommendations(
        TEST_USER_ID, 10, nmemes_sent=0, retriever=TestRetriever()
    )
    assert len(candidates) == 2
    assert candidates[0]["id"] in [301, 302]


@pytest.mark.asyncio
async def test_cold_start_phase1_fallback_to_uploaded():
    """Phase 1 + text_light_lr_smoothed both empty → fallback to best_uploaded_memes"""

    async def empty(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return []

    async def best_uploaded(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 401}]

    class TestRetriever(CandidatesRetriever):
        engine_map = {
            "cold_start_explore": empty,
            "cold_start_adapt": empty,
            "text_light_lr_smoothed": empty,
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
    """Phase 2 empty → fallback to text_light_lr_smoothed"""

    async def empty(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return []

    async def text_light_lr_smoothed(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 301}]

    async def best_uploaded(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 401}]

    class TestRetriever(CandidatesRetriever):
        engine_map = {
            "cold_start_explore": empty,
            "cold_start_adapt": empty,
            "text_light_lr_smoothed": text_light_lr_smoothed,
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
            "text_light_lr_smoothed": lr_smoothed,
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
    captured_weights = None

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

    def capture_blend(candidates_dict, weights_dict, fixed_pos=None, limit=0, random_seed=None):
        nonlocal captured_weights
        captured_weights = weights_dict
        from src.recommendations.blender import blend

        return blend(candidates_dict, weights_dict, fixed_pos, limit, random_seed)

    with (
        patch("src.recommendations.meme_queue.blend", side_effect=capture_blend),
        patch(
            "src.recommendations.meme_queue.get_recently_liked_blender_v2_weights",
            new_callable=AsyncMock,
            return_value=MATURE_BLENDER_CONTROL_WEIGHTS,
        ) as get_weights,
    ):
        candidates = await generate_recommendations(
            TEST_USER_ID, 10, 200, TestRetriever(), random_seed=102
        )

    assert len(candidates) == 10
    # lr_smoothed is pinned at position 0
    assert candidates[0]["id"] in [7, 8, 9, 10]
    assert captured_weights == MATURE_BLENDER_CONTROL_WEIGHTS
    get_weights.assert_awaited_once_with(TEST_USER_ID)


@pytest.mark.asyncio
async def test_generate_above_100_treatment_uses_recently_liked_weights():
    captured_weights = None

    async def one_candidate(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 4, "recommended_by": "recently_liked"}]

    class TestRetriever(CandidatesRetriever):
        engine_map = {
            "best_uploaded_memes": one_candidate,
            "like_spread_and_recent_memes": one_candidate,
            "lr_smoothed": one_candidate,
            "recently_liked": one_candidate,
            "goat": one_candidate,
            "es_ranked": one_candidate,
        }

    def capture_blend(candidates_dict, weights_dict, fixed_pos=None, limit=0, random_seed=None):
        nonlocal captured_weights
        captured_weights = weights_dict
        return [{"id": 4, "recommended_by": "recently_liked"}]

    with (
        patch(
            "src.recommendations.meme_queue.get_recently_liked_blender_v2_weights",
            new_callable=AsyncMock,
            return_value=MATURE_BLENDER_TREATMENT_WEIGHTS,
        ) as get_weights,
        patch("src.recommendations.meme_queue.blend", side_effect=capture_blend),
    ):
        candidates = await generate_recommendations(
            TEST_USER_ID, 10, 200, TestRetriever(), random_seed=102
        )

    assert candidates == [{"id": 4, "recommended_by": "recently_liked"}]
    assert captured_weights == MATURE_BLENDER_TREATMENT_WEIGHTS
    assert captured_weights["recently_liked"] > MATURE_BLENDER_CONTROL_WEIGHTS["recently_liked"]
    get_weights.assert_awaited_once_with(TEST_USER_ID)


@pytest.mark.asyncio
async def test_text_light_blender_v1_is_disabled_in_queue_generation():
    captured_weights = None
    captured_fixed_pos = None

    async def one_candidate(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 4, "recommended_by": "generic"}]

    class TestRetriever(CandidatesRetriever):
        engine_map = {
            "best_uploaded_memes": one_candidate,
            "like_spread_and_recent_memes": one_candidate,
            "lr_smoothed": one_candidate,
            "recently_liked": one_candidate,
            "goat": one_candidate,
            "es_ranked": one_candidate,
        }

    treatment_weights = dict(MATURE_BLENDER_CONTROL_WEIGHTS)
    lr_weight = treatment_weights.pop("lr_smoothed")
    treatment_weights["text_light_lr_smoothed"] = lr_weight

    def capture_blend(candidates_dict, weights_dict, fixed_pos=None, limit=0, random_seed=None):
        nonlocal captured_weights, captured_fixed_pos
        captured_weights = weights_dict
        captured_fixed_pos = fixed_pos
        return [{"id": 4, "recommended_by": "lr_smoothed"}]

    with (
        patch(
            "src.recommendations.meme_queue.get_recently_liked_blender_v2_weights",
            new_callable=AsyncMock,
            return_value=MATURE_BLENDER_CONTROL_WEIGHTS,
        ),
        patch(
            "src.recommendations.meme_queue.get_text_light_blender_v1_weights",
            new_callable=AsyncMock,
            return_value=treatment_weights,
        ) as get_text_light_weights,
        patch("src.recommendations.meme_queue.blend", side_effect=capture_blend),
    ):
        candidates = await generate_recommendations(
            TEST_USER_ID, 10, 200, TestRetriever(), random_seed=102
        )

    assert candidates == [{"id": 4, "recommended_by": "lr_smoothed"}]
    assert captured_weights == MATURE_BLENDER_CONTROL_WEIGHTS
    assert captured_fixed_pos == {0: "lr_smoothed"}
    get_text_light_weights.assert_not_awaited()


@pytest.mark.asyncio
async def test_recently_liked_blender_v2_assignment_is_mature_only():
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
            "text_light_lr_smoothed": empty,
        }

    with patch(
        "src.recommendations.meme_queue.get_recently_liked_blender_v2_weights",
        new_callable=AsyncMock,
        return_value=MATURE_BLENDER_TREATMENT_WEIGHTS,
    ) as get_weights:
        await generate_recommendations(TEST_USER_ID, 10, 29, TestRetriever())
        await generate_recommendations(TEST_USER_ID, 10, 99, TestRetriever())

    get_weights.assert_not_awaited()


@pytest.mark.asyncio
async def test_recently_liked_blender_v2_skips_moderator_assignment():
    async def one_candidate(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 4, "recommended_by": "recently_liked"}]

    class TestRetriever(CandidatesRetriever):
        engine_map = {
            "best_uploaded_memes": one_candidate,
            "like_spread_and_recent_memes": one_candidate,
            "lr_smoothed": one_candidate,
            "recently_liked": one_candidate,
            "goat": one_candidate,
            "es_ranked": one_candidate,
        }

    captured_weights = None

    def capture_blend(candidates_dict, weights_dict, fixed_pos=None, limit=0, random_seed=None):
        nonlocal captured_weights
        captured_weights = weights_dict
        return [{"id": 4, "recommended_by": "recently_liked"}]

    with (
        patch(
            "src.recommendations.meme_queue.get_recently_liked_blender_v2_weights",
            new_callable=AsyncMock,
            return_value=MATURE_BLENDER_TREATMENT_WEIGHTS,
        ) as get_weights,
        patch(
            "src.recommendations.meme_queue.get_user_info",
            new_callable=AsyncMock,
            return_value={"nmemes_sent": 200, "type": "moderator"},
        ),
        patch(
            "src.recommendations.meme_queue.fetch_all",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch("src.recommendations.meme_queue.blend", side_effect=capture_blend),
    ):
        candidates = await generate_recommendations(
            TEST_USER_ID, 1, 200, TestRetriever(), random_seed=102
        )

    assert candidates == [{"id": 4, "recommended_by": "recently_liked"}]
    assert captured_weights == MATURE_BLENDER_CONTROL_WEIGHTS
    get_weights.assert_not_awaited()


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
        "src.recommendations.meme_queue.get_recently_liked_blender_v2_weights",
        new_callable=AsyncMock,
        return_value=MATURE_BLENDER_CONTROL_WEIGHTS,
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
            "text_light_lr_smoothed": empty,
            "lr_smoothed": empty,
            "best_uploaded_memes": empty,
            "like_spread_and_recent_memes": empty,
        }

    for nmemes in [0, 3, 8, 12, 20, 25]:
        candidates = await generate_recommendations(TEST_USER_ID, 10, nmemes, TestRetriever())
        assert len(candidates) == 0, f"Expected empty at nmemes_sent={nmemes}"


# ── FFM-1161: nsessions gate ──


def _growing_retriever_class():
    """Retriever covering both cold_start engines and the growing-user blender."""

    async def cold_start_explore(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 101, "recommended_by": "cold_start_explore"}]

    async def cold_start_adapt(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 201, "recommended_by": "cold_start_adapt"}]

    async def lr_smoothed(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 301, "recommended_by": "lr_smoothed"}]

    async def text_light_lr_smoothed(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 302, "recommended_by": "text_light_lr_smoothed"}]

    async def best_uploaded_memes(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 401, "recommended_by": "best_uploaded_memes"}]

    async def like_spread_and_recent_memes(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 501, "recommended_by": "like_spread_and_recent_memes"}]

    async def recently_liked(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 601, "recommended_by": "recently_liked"}]

    async def goat(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 701, "recommended_by": "goat"}]

    async def es_ranked(self, user_id, limit=10, exclude_meme_ids=[], **kw):
        return [{"id": 801, "recommended_by": "es_ranked"}]

    class TestRetriever(CandidatesRetriever):
        engine_map = {
            "cold_start_explore": cold_start_explore,
            "cold_start_adapt": cold_start_adapt,
            "text_light_lr_smoothed": text_light_lr_smoothed,
            "lr_smoothed": lr_smoothed,
            "best_uploaded_memes": best_uploaded_memes,
            "like_spread_and_recent_memes": like_spread_and_recent_memes,
            "recently_liked": recently_liked,
            "goat": goat,
            "es_ranked": es_ranked,
        }

    return TestRetriever


@pytest.mark.asyncio
async def test_gate_off_dormant_returner_still_uses_cold_start():
    """Emergency override off: nsessions is ignored and cold_start routes by nmemes_sent."""
    retriever = _growing_retriever_class()()
    with (
        _patch_user_info(nsessions=5, nmemes_sent=8),
        patch("src.config.settings.COLD_START_NSESSIONS_GATE_ENABLED", False),
    ):
        candidates = await generate_recommendations(
            TEST_USER_ID, 10, nmemes_sent=8, retriever=retriever
        )
    assert any(c["recommended_by"] == "cold_start_adapt" for c in candidates)


@pytest.mark.asyncio
async def test_gate_default_blocks_dormant_returner_from_cold_start():
    """Default config blocks nsessions>=2 low-sent users from cold_start engines."""
    retriever = _growing_retriever_class()()
    with _patch_user_info(nsessions=3, nmemes_sent=8):
        candidates = await generate_recommendations(
            TEST_USER_ID, 10, nmemes_sent=8, retriever=retriever, random_seed=42
        )

    sources = {c["recommended_by"] for c in candidates}
    assert "cold_start_explore" not in sources
    assert "cold_start_adapt" not in sources
    assert candidates[0]["recommended_by"] == "lr_smoothed"


@pytest.mark.asyncio
async def test_gate_default_blocks_old_low_sent_user_from_cold_start():
    """Old accounts can be dormant returners even before nsessions increments."""
    retriever = _growing_retriever_class()()
    with _patch_user_info(
        nsessions=1,
        nmemes_sent=8,
        account_age_days=30,
        cold_start_account_too_old=True,
    ):
        candidates = await generate_recommendations(
            TEST_USER_ID, 10, nmemes_sent=8, retriever=retriever, random_seed=42
        )

    sources = {c["recommended_by"] for c in candidates}
    assert "cold_start_explore" not in sources
    assert "cold_start_adapt" not in sources
    assert candidates[0]["recommended_by"] == "lr_smoothed"


@pytest.mark.asyncio
async def test_gate_default_blocks_realtime_second_session_even_when_cache_is_stale():
    """Realtime sent history catches dormant returners before user_info/user_stats catches up."""
    retriever = _growing_retriever_class()()
    stale_cached_state = {
        "account_age_days": 28,
        "cold_start_account_too_old": False,
        "prior_sent_count": 26,
        "nsessions_after_next_send": 2,
    }
    with (
        _patch_user_info(nsessions=1, nmemes_sent=26, cold_start_account_too_old=False),
        patch(
            "src.recommendations.meme_queue._get_realtime_cold_start_routing_state",
            new_callable=AsyncMock,
            return_value=stale_cached_state,
        ) as realtime_state,
    ):
        candidates = await generate_recommendations(
            TEST_USER_ID, 10, nmemes_sent=26, retriever=retriever, random_seed=42
        )

    sources = {c["recommended_by"] for c in candidates}
    assert "cold_start_explore" not in sources
    assert "cold_start_adapt" not in sources
    assert candidates[0]["recommended_by"] == "lr_smoothed"
    realtime_state.assert_awaited_once_with(TEST_USER_ID)


@pytest.mark.asyncio
async def test_gate_default_keeps_exact_30_day_low_sent_user_in_cold_start():
    """The age gate uses the exact timestamp threshold, not floored account_age_days."""
    retriever = _growing_retriever_class()()
    with _patch_user_info(
        nsessions=1,
        nmemes_sent=8,
        account_age_days=30,
        cold_start_account_too_old=False,
    ):
        candidates = await generate_recommendations(
            TEST_USER_ID, 10, nmemes_sent=8, retriever=retriever, random_seed=42
        )

    assert any(c["recommended_by"] == "cold_start_adapt" for c in candidates)


@pytest.mark.asyncio
async def test_gate_on_first_session_routes_to_cold_start_explore():
    """Gate on + nsessions<=1 + nmemes_sent<6 → cold_start_explore (Phase 1)."""
    retriever = _growing_retriever_class()()
    with (
        _patch_user_info(nsessions=0, nmemes_sent=0),
        patch("src.config.settings.COLD_START_NSESSIONS_GATE_ENABLED", True),
    ):
        candidates = await generate_recommendations(
            TEST_USER_ID, 10, nmemes_sent=0, retriever=retriever
        )
    assert candidates[0]["recommended_by"] == "cold_start_explore"


@pytest.mark.asyncio
async def test_gate_on_first_session_phase2_routes_to_cold_start_adapt():
    """Gate on + nsessions<=1 + 6<=nmemes_sent<16 → cold_start_adapt (Phase 2)."""
    retriever = _growing_retriever_class()()
    with (
        _patch_user_info(nsessions=1, nmemes_sent=8),
        patch("src.config.settings.COLD_START_NSESSIONS_GATE_ENABLED", True),
    ):
        candidates = await generate_recommendations(
            TEST_USER_ID, 10, nmemes_sent=8, retriever=retriever
        )
    assert any(c["recommended_by"] == "cold_start_adapt" for c in candidates)


@pytest.mark.asyncio
async def test_gate_on_dormant_returner_falls_through_to_growing_blender():
    """Gate on + nsessions>=2 + nmemes_sent<30 → growing-user blender, NO cold_start engines."""
    retriever = _growing_retriever_class()()
    with (
        _patch_user_info(nsessions=3, nmemes_sent=12),
        patch("src.config.settings.COLD_START_NSESSIONS_GATE_ENABLED", True),
    ):
        candidates = await generate_recommendations(
            TEST_USER_ID, 10, nmemes_sent=12, retriever=retriever, random_seed=42
        )
    sources = {c["recommended_by"] for c in candidates}
    assert "cold_start_explore" not in sources
    assert "cold_start_adapt" not in sources
    # Growing blender is pinned at lr_smoothed in position 0
    assert candidates[0]["recommended_by"] == "lr_smoothed"


@pytest.mark.asyncio
async def test_gate_on_mature_user_unchanged():
    """Gate on + mature user (nmemes_sent>=100) → blender_v2 path, untouched by gate."""
    retriever = _growing_retriever_class()()
    with (
        _patch_user_info(nsessions=5, nmemes_sent=120),
        patch("src.config.settings.COLD_START_NSESSIONS_GATE_ENABLED", True),
        patch(
            "src.recommendations.meme_queue.get_recently_liked_blender_v2_weights",
            new_callable=AsyncMock,
            return_value=MATURE_BLENDER_TREATMENT_WEIGHTS,
        ) as get_weights,
    ):
        candidates = await generate_recommendations(
            TEST_USER_ID, 10, nmemes_sent=120, retriever=retriever, random_seed=42
        )
    sources = {c["recommended_by"] for c in candidates}
    assert "cold_start_explore" not in sources
    assert "cold_start_adapt" not in sources
    get_weights.assert_awaited_once_with(TEST_USER_ID)


@pytest.mark.asyncio
async def test_gate_on_missing_nsessions_treated_as_zero():
    """Stale cache without nsessions key → treated as 0, cold_start still applies."""
    retriever = _growing_retriever_class()()
    # user_info lacks 'nsessions' (defaultdict(int) returns 0)
    stale_info = defaultdict(int, {"nmemes_sent": 4})
    with (
        patch(
            "src.recommendations.meme_queue.get_user_info",
            new_callable=AsyncMock,
            return_value=stale_info,
        ),
        patch("src.config.settings.COLD_START_NSESSIONS_GATE_ENABLED", True),
    ):
        candidates = await generate_recommendations(
            TEST_USER_ID, 10, nmemes_sent=4, retriever=retriever
        )
    assert candidates[0]["recommended_by"] == "cold_start_explore"
