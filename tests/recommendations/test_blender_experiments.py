from unittest.mock import AsyncMock, patch

import pytest

from src.recommendations.blender_experiments import (
    EXPLORE_BUDGET_V1_CONTROL,
    EXPLORE_BUDGET_V1_EXPERIMENT_ID,
    EXPLORE_BUDGET_V1_TREATMENT,
    explore_budget_v1_variant_for_user,
    is_explore_budget_v1_treatment,
)


def test_explore_budget_v1_split_is_deterministic_and_balanced():
    variants = [explore_budget_v1_variant_for_user(user_id) for user_id in range(2000)]

    assert variants == [explore_budget_v1_variant_for_user(u) for u in range(2000)]
    assert 900 < variants.count(EXPLORE_BUDGET_V1_TREATMENT) < 1100


@pytest.mark.asyncio
async def test_explore_budget_v1_assigns_hash_variant_once_and_skips_cold_start():
    treated = EXPLORE_BUDGET_V1_TREATMENT
    user_id = next(u for u in range(100) if explore_budget_v1_variant_for_user(u) == treated)
    with (
        patch(
            "src.recommendations.blender_experiments.get_experiment_assignment",
            new_callable=AsyncMock,
            return_value=None,
        ) as get_assignment,
        patch(
            "src.recommendations.blender_experiments.assign_experiment",
            new_callable=AsyncMock,
            return_value=True,
        ) as assign,
    ):
        assert await is_explore_budget_v1_treatment(user_id, 29) is False
        get_assignment.assert_not_awaited()

        assert await is_explore_budget_v1_treatment(user_id, 30) is True
        assert assign.await_args.args[:3] == (
            user_id,
            EXPLORE_BUDGET_V1_EXPERIMENT_ID,
            EXPLORE_BUDGET_V1_TREATMENT,
        )

        get_assignment.return_value = {"variant": EXPLORE_BUDGET_V1_CONTROL}
        assert await is_explore_budget_v1_treatment(user_id, 500) is False
        assert assign.await_count == 1
