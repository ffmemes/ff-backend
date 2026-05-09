from unittest.mock import AsyncMock, patch

import pytest

from src.recommendations.blender_experiments import (
    MATURE_BLENDER_CONTROL_WEIGHTS,
    MATURE_BLENDER_TREATMENT_WEIGHTS,
    RECENTLY_LIKED_BLENDER_V2_CONTROL,
    RECENTLY_LIKED_BLENDER_V2_DEFAULT_QUARTILE_BOUNDARIES,
    RECENTLY_LIKED_BLENDER_V2_EXCLUDED,
    RECENTLY_LIKED_BLENDER_V2_EXPERIMENT_ID,
    RECENTLY_LIKED_BLENDER_V2_SAMPLE_GATE_PER_VARIANT,
    RECENTLY_LIKED_BLENDER_V2_TREATMENT,
    _lr_quartile_from_boundaries,
    build_recently_liked_blender_v2_assignment,
    get_or_assign_recently_liked_blender_v2_variant,
    get_recent_7d_lr_assignment_metrics,
    get_recent_7d_lr_quartile_boundaries,
    get_recently_liked_blender_v2_weights,
)


def test_assignment_excludes_high_volume_low_lr_skipper():
    variant, metadata = build_recently_liked_blender_v2_assignment(
        101,
        {
            "likes_7d": 9,
            "reactions_7d": 51,
            "lr_7d": 9 / 51,
            "lr_quartile": 1,
        },
    )

    assert variant == RECENTLY_LIKED_BLENDER_V2_EXCLUDED
    assert metadata["high_volume_skipper"] is True
    assert metadata["excluded_reason"] == "lr_7d_below_20pct_and_reactions_7d_above_50"
    assert metadata["assigned_weights"] == MATURE_BLENDER_CONTROL_WEIGHTS


def test_assignment_persists_stratification_metadata_for_eligible_user():
    variant, metadata = build_recently_liked_blender_v2_assignment(
        202,
        {
            "likes_7d": 20,
            "reactions_7d": 60,
            "lr_7d": 1 / 3,
            "lr_quartile": 2,
        },
    )

    assert variant in {RECENTLY_LIKED_BLENDER_V2_CONTROL, RECENTLY_LIKED_BLENDER_V2_TREATMENT}
    assert metadata["lr_quartile"] == 2
    assert metadata["reactions_7d"] == 60
    assert metadata["high_volume_skipper"] is False
    assert metadata["sample_gate_per_variant"] == RECENTLY_LIKED_BLENDER_V2_SAMPLE_GATE_PER_VARIANT
    assert metadata["day3_guardrail"]["primary_read_rule"] == "sample_gate_per_variant"


def test_assignment_is_stable_within_lr_quartile():
    metrics = {
        "likes_7d": 20,
        "reactions_7d": 60,
        "lr_7d": 1 / 3,
        "lr_quartile": 3,
    }

    first, first_metadata = build_recently_liked_blender_v2_assignment(303, metrics)
    second, second_metadata = build_recently_liked_blender_v2_assignment(303, metrics)

    assert first == second
    assert first_metadata == second_metadata


def test_lr_quartile_uses_cached_boundaries():
    boundaries = (0.2, 0.5, 0.8)

    assert _lr_quartile_from_boundaries(0.2, boundaries) == 1
    assert _lr_quartile_from_boundaries(0.21, boundaries) == 2
    assert _lr_quartile_from_boundaries(0.51, boundaries) == 3
    assert _lr_quartile_from_boundaries(0.81, boundaries) == 4


@pytest.mark.asyncio
async def test_lr_assignment_metrics_only_fetch_current_user_reactions():
    with (
        patch(
            "src.recommendations.blender_experiments.get_recent_7d_lr_quartile_boundaries",
            new_callable=AsyncMock,
            return_value=(0.2, 0.5, 0.8),
        ) as get_boundaries,
        patch(
            "src.recommendations.blender_experiments.fetch_one",
            new_callable=AsyncMock,
            return_value={"likes_7d": 35, "reactions_7d": 100, "lr_7d": 0.35},
        ) as fetch_metrics,
    ):
        metrics = await get_recent_7d_lr_assignment_metrics(101)

    get_boundaries.assert_awaited_once()
    fetch_metrics.assert_awaited_once()
    query_text = str(fetch_metrics.await_args.args[0])
    assert "NTILE" not in query_text
    assert "GROUP BY umr.user_id" not in query_text
    assert metrics == {
        "likes_7d": 35,
        "reactions_7d": 100,
        "lr_7d": 0.35,
        "lr_quartile": 2,
        "lr_quartile_boundaries": [0.2, 0.5, 0.8],
    }


@pytest.mark.asyncio
async def test_lr_quartile_boundaries_do_not_recompute_without_cache_lock():
    with (
        patch(
            "src.recommendations.blender_experiments._get_cached_lr_quartile_boundaries",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.recommendations.blender_experiments.redis_client.set",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.recommendations.blender_experiments.sleep",
            new_callable=AsyncMock,
        ),
        patch(
            "src.recommendations.blender_experiments._calculate_recent_7d_lr_quartile_boundaries",
            new_callable=AsyncMock,
        ) as calculate_boundaries,
    ):
        boundaries = await get_recent_7d_lr_quartile_boundaries()

    assert boundaries == RECENTLY_LIKED_BLENDER_V2_DEFAULT_QUARTILE_BOUNDARIES
    calculate_boundaries.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_recently_liked_blender_v2_assignment_wins():
    with patch(
        "src.recommendations.blender_experiments.get_experiment_assignment",
        new_callable=AsyncMock,
        return_value={"variant": RECENTLY_LIKED_BLENDER_V2_TREATMENT},
    ) as get_assignment:
        variant = await get_or_assign_recently_liked_blender_v2_variant(101)

    assert variant == RECENTLY_LIKED_BLENDER_V2_TREATMENT
    get_assignment.assert_awaited_once_with(101, RECENTLY_LIKED_BLENDER_V2_EXPERIMENT_ID)


@pytest.mark.asyncio
async def test_recently_liked_blender_v2_race_rereads_winning_assignment():
    with (
        patch(
            "src.recommendations.blender_experiments.get_experiment_assignment",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.recommendations.blender_experiments.get_recent_7d_lr_assignment_metrics",
            new_callable=AsyncMock,
            return_value={
                "likes_7d": 20,
                "reactions_7d": 60,
                "lr_7d": 1 / 3,
                "lr_quartile": 2,
            },
        ),
        patch(
            "src.recommendations.blender_experiments.assign_experiment",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "src.recommendations.blender_experiments.get_experiment_variant",
            new_callable=AsyncMock,
            return_value=RECENTLY_LIKED_BLENDER_V2_CONTROL,
        ),
    ):
        variant = await get_or_assign_recently_liked_blender_v2_variant(202)

    assert variant == RECENTLY_LIKED_BLENDER_V2_CONTROL


@pytest.mark.asyncio
async def test_recently_liked_blender_v2_weights_fall_back_to_control_on_assignment_error():
    with patch(
        "src.recommendations.blender_experiments.get_or_assign_recently_liked_blender_v2_variant",
        new_callable=AsyncMock,
        side_effect=RuntimeError("assignment unavailable"),
    ):
        weights = await get_recently_liked_blender_v2_weights(100)

    assert weights == MATURE_BLENDER_CONTROL_WEIGHTS


@pytest.mark.asyncio
async def test_recently_liked_blender_v2_treatment_increases_recently_liked_weight():
    with patch(
        "src.recommendations.blender_experiments.get_or_assign_recently_liked_blender_v2_variant",
        new_callable=AsyncMock,
        return_value=RECENTLY_LIKED_BLENDER_V2_TREATMENT,
    ):
        weights = await get_recently_liked_blender_v2_weights(100)

    assert weights == MATURE_BLENDER_TREATMENT_WEIGHTS
    assert weights["recently_liked"] > MATURE_BLENDER_CONTROL_WEIGHTS["recently_liked"]
    assert weights["lr_smoothed"] < MATURE_BLENDER_CONTROL_WEIGHTS["lr_smoothed"]
