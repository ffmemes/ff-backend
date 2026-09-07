from unittest.mock import AsyncMock, patch

import pytest

from src.recommendations.candidates import (
    COLD_START_EXPLORE_FRESH_GUARDED_RECOMMENDED_BY,
    COLD_START_EXPLORE_FRESH_RECOMMENDED_BY,
    cold_start_explore,
)
from src.recommendations.cold_start_experiments import (
    COLD_START_FRESH_MAX_AGE_DAYS,
    COLD_START_FRESH_VIRAL_CONTROL,
    COLD_START_FRESH_VIRAL_TREATMENT,
    cold_start_fresh_variant_for_user,
    fresh_max_age_days_for_variant,
    is_cold_start_fresh_eligible,
)
from src.recommendations.pipeline import (
    RecommendationBatchPipeline,
    RecommendationBatchRequest,
)


def _fetch_call_sql_and_params(fetch_all: AsyncMock) -> tuple[str, dict]:
    query, params = fetch_all.call_args.args
    return str(query), params


def test_fresh_variant_is_stable_split():
    control_ids = [
        user_id
        for user_id in range(200)
        if cold_start_fresh_variant_for_user(user_id) == COLD_START_FRESH_VIRAL_CONTROL
    ]
    treatment_ids = [
        user_id
        for user_id in range(200)
        if cold_start_fresh_variant_for_user(user_id) == COLD_START_FRESH_VIRAL_TREATMENT
    ]
    assert len(control_ids) > 40
    assert len(treatment_ids) > 40
    assert cold_start_fresh_variant_for_user(control_ids[0]) == COLD_START_FRESH_VIRAL_CONTROL
    assert cold_start_fresh_variant_for_user(treatment_ids[0]) == COLD_START_FRESH_VIRAL_TREATMENT


def test_fresh_eligibility_and_max_age():
    assert is_cold_start_fresh_eligible(0, 1, False) is True
    assert is_cold_start_fresh_eligible(6, 1, False) is False
    assert is_cold_start_fresh_eligible(0, 2, False) is False
    assert is_cold_start_fresh_eligible(0, 1, True) is False
    assert (
        fresh_max_age_days_for_variant(
            COLD_START_FRESH_VIRAL_TREATMENT,
            nmemes_sent=0,
            nsessions=1,
            cold_start_account_too_old=False,
        )
        == COLD_START_FRESH_MAX_AGE_DAYS
    )
    assert (
        fresh_max_age_days_for_variant(
            COLD_START_FRESH_VIRAL_CONTROL,
            nmemes_sent=0,
            nsessions=1,
            cold_start_account_too_old=False,
        )
        is None
    )


@pytest.mark.asyncio
async def test_cold_start_explore_fresh_filters_age_and_ranks_newest():
    with patch(
        "src.recommendations.candidates.fetch_all",
        new_callable=AsyncMock,
        return_value=[],
    ) as fetch_all:
        await cold_start_explore(123, limit=5, max_age_days=30)

    query_sql, params = _fetch_call_sql_and_params(fetch_all)
    assert "cold_start_max_age_days" in query_sql
    assert params["cold_start_max_age_days"] == 30
    assert params["recommended_by"] == COLD_START_EXPLORE_FRESH_RECOMMENDED_BY
    assert "M.created_at DESC" in query_sql


@pytest.mark.asyncio
async def test_cold_start_explore_fresh_guarded_label():
    with patch(
        "src.recommendations.candidates.fetch_all",
        new_callable=AsyncMock,
        return_value=[],
    ) as fetch_all:
        await cold_start_explore(
            123,
            limit=5,
            max_age_days=30,
            candidate_guardrails_enabled=True,
        )

    _, params = _fetch_call_sql_and_params(fetch_all)
    assert params["recommended_by"] == COLD_START_EXPLORE_FRESH_GUARDED_RECOMMENDED_BY


@pytest.mark.asyncio
async def test_generate_recommendations_passes_fresh_max_age_for_treatment():
    from src.recommendations.meme_queue import generate_recommendations

    retriever = AsyncMock()
    retriever.get_candidates = AsyncMock(return_value=[])
    retriever.get_candidates_dict = AsyncMock(return_value={})

    with (
        patch(
            "src.recommendations.meme_queue.get_user_info",
            new_callable=AsyncMock,
            return_value={"nmemes_sent": 0, "nsessions": 1, "type": "user"},
        ),
        patch(
            "src.recommendations.meme_queue.redis.get_all_memes_in_queue_by_key",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.recommendations.meme_queue.get_or_assign_cold_start_fresh_variant",
            new_callable=AsyncMock,
            return_value=COLD_START_FRESH_VIRAL_TREATMENT,
        ),
        patch("src.recommendations.meme_queue.settings") as settings,
        patch(
            "src.recommendations.meme_queue.RecommendationBatchPipeline.run",
            new_callable=AsyncMock,
        ) as run,
    ):
        settings.COLD_START_FRESH_VIRAL_EXPERIMENT_ENABLED = True
        settings.COLD_START_NSESSIONS_GATE_ENABLED = False
        settings.COLD_START_CANDIDATE_GUARDRAILS_ENABLED = False
        settings.RECOMMENDATION_SOURCE_DIVERSITY_ENABLED = False
        settings.RECOMMENDATION_SHADOW_SCORING_ENABLED = False
        settings.RECOMMENDATION_DIAGNOSTICS_SAMPLE_RATE = 0.0
        run.return_value.selected = []
        await generate_recommendations(7, limit=5, nmemes_sent=0, retriever=retriever)

    request = run.await_args.args[0]
    assert request.cold_start_fresh_max_age_days == COLD_START_FRESH_MAX_AGE_DAYS


@pytest.mark.asyncio
async def test_pipeline_prefers_fresh_then_fills_classic_cs():
    retriever = AsyncMock()

    async def get_candidates(engine, user_id, limit, exclude_mem_ids=None, **kwargs):
        if kwargs.get("max_age_days"):
            return [{"id": 1, "recommended_by": "cold_start_explore_fresh"}]
        return [
            {"id": 1, "recommended_by": "cold_start_explore"},
            {"id": 2, "recommended_by": "cold_start_explore"},
            {"id": 3, "recommended_by": "cold_start_explore"},
        ]

    retriever.get_candidates.side_effect = get_candidates
    pipeline = RecommendationBatchPipeline(retriever=retriever)
    result = await pipeline.run(
        RecommendationBatchRequest(
            user_id=7,
            limit=3,
            nmemes_sent=0,
            nsessions=1,
            cold_start_fresh_max_age_days=30,
        )
    )

    assert [row["id"] for row in result.selected] == [1, 2, 3]
    assert result.selected[0]["recommended_by"] == "cold_start_explore_fresh"
    assert result.diagnostics.cold_start_fresh_applied is True
    assert retriever.get_candidates.await_count >= 2
