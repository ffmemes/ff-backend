import json
from typing import Any

import pytest

from src.recommendations.pipeline import (
    RecommendationBatchPipeline,
    RecommendationBatchRequest,
)

TEST_USER_ID = 99999


def _meme(
    meme_id: int,
    recommended_by: str = "lr_smoothed",
    meme_source_id: int | None = None,
) -> dict[str, Any]:
    meme: dict[str, Any] = {
        "id": meme_id,
        "type": "image",
        "telegram_file_id": f"file_{meme_id}",
        "caption": None,
        "recommended_by": recommended_by,
        "nlikes": 10,
    }
    if meme_source_id is not None:
        meme["meme_source_id"] = meme_source_id
    return meme


class FakeRetriever:
    def __init__(
        self,
        candidates_by_engine: dict[str, list[dict[str, Any]]],
        failing_engines: set[str] | None = None,
    ) -> None:
        self.candidates_by_engine = candidates_by_engine
        self.failing_engines = failing_engines or set()
        self.calls: list[dict[str, Any]] = []
        self.engine_errors: dict[str, str] = {}

    async def get_candidates(
        self,
        engine: str,
        user_id: int,
        limit: int = 10,
        exclude_mem_ids: list[int] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        exclude_mem_ids = exclude_mem_ids or []
        self.calls.append(
            {
                "method": "get_candidates",
                "engine": engine,
                "user_id": user_id,
                "limit": limit,
                "exclude_mem_ids": list(exclude_mem_ids),
                "kwargs": kwargs,
            }
        )

        if engine in self.failing_engines:
            raise RuntimeError(f"{engine} is temporarily unavailable")

        excluded = set(exclude_mem_ids)
        candidates = [
            candidate.copy()
            for candidate in self.candidates_by_engine.get(engine, [])
            if candidate["id"] not in excluded
        ]
        return candidates[:limit]

    async def get_candidates_dict(
        self,
        engines: list[str],
        user_id: int,
        limit: int = 10,
        exclude_mem_ids: list[int] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        candidates_by_engine: dict[str, list[dict[str, Any]]] = {}
        for engine in engines:
            try:
                candidates_by_engine[engine] = await self.get_candidates(
                    engine,
                    user_id,
                    limit,
                    exclude_mem_ids,
                )
            except RuntimeError as exc:
                self.engine_errors[engine] = str(exc)
                candidates_by_engine[engine] = []
        return candidates_by_engine


def _fake_blend(
    candidates_by_engine: dict[str, list[dict[str, Any]]],
    weights: dict[str, float],
    fixed_pos: dict[int, str] | None = None,
    limit: int = 0,
    random_seed: int | None = None,
) -> list[dict[str, Any]]:
    del weights, fixed_pos, random_seed
    blended: list[dict[str, Any]] = []
    for candidates in candidates_by_engine.values():
        blended.extend(candidate.copy() for candidate in candidates)
    return blended[:limit] if limit else blended


async def _empty_low_sent_fetcher(
    request: RecommendationBatchRequest,
    limit: int,
    exclude_meme_ids: list[int],
) -> list[dict[str, Any]]:
    del request, limit, exclude_meme_ids
    return []


async def _identity_text_light_weights(
    user_id: int,
    weights: dict[str, float],
) -> dict[str, float]:
    del user_id
    return weights


def _pipeline(
    retriever: FakeRetriever,
    *,
    low_sent_fetcher=_empty_low_sent_fetcher,
    shadow_scorer=None,
) -> RecommendationBatchPipeline:
    return RecommendationBatchPipeline(
        retriever=retriever,
        blend_func=_fake_blend,
        low_sent_fetcher=low_sent_fetcher,
        shadow_scorer=shadow_scorer,
        text_light_weights_func=_identity_text_light_weights,
    )


def _request(**overrides: Any) -> RecommendationBatchRequest:
    params: dict[str, Any] = {
        "user_id": TEST_USER_ID,
        "limit": 5,
        "nmemes_sent": 50,
        "nsessions": 2,
        "meme_ids_in_queue": [],
    }
    params.update(overrides)
    return RecommendationBatchRequest(**params)


def _ids(candidates: list[dict[str, Any]]) -> list[int]:
    return [candidate["id"] for candidate in candidates]


@pytest.mark.asyncio
async def test_cold_start_falls_back_when_primary_engine_is_empty():
    retriever = FakeRetriever(
        {
            "cold_start_explore": [],
            "text_light_lr_smoothed": [_meme(301), _meme(302)],
            "best_uploaded_memes": [_meme(401, "best_uploaded_memes")],
        }
    )

    result = await _pipeline(retriever).run(_request(nmemes_sent=3, nsessions=1))

    assert _ids(result.selected) == [301, 302]
    assert [call["engine"] for call in retriever.calls] == [
        "cold_start_explore",
        "text_light_lr_smoothed",
    ]
    assert "cold_start_explore" in repr(result.diagnostics)
    assert "text_light_lr_smoothed" in repr(result.diagnostics)


@pytest.mark.asyncio
async def test_fallback_diagnostics_record_engine_that_supplied_candidates():
    retriever = FakeRetriever(
        {
            "cold_start_explore": [],
            "text_light_lr_smoothed": [],
            "best_uploaded_memes": [_meme(401, "best_uploaded_memes")],
        }
    )

    result = await _pipeline(retriever).run(_request(nmemes_sent=3, nsessions=1))

    assert _ids(result.selected) == [401]
    assert [call["engine"] for call in retriever.calls] == [
        "cold_start_explore",
        "text_light_lr_smoothed",
        "best_uploaded_memes",
    ]
    assert result.diagnostics.fallback_used == "best_uploaded_memes"


@pytest.mark.asyncio
async def test_cold_start_guardrails_apply_to_true_new_positions_2_to_10():
    retriever = FakeRetriever(
        {
            "cold_start_explore": [_meme(101, "cold_start_explore_guarded")],
            "text_light_lr_smoothed": [_meme(301, "text_light_lr_smoothed")],
        }
    )

    result = await _pipeline(retriever).run(
        _request(
            nmemes_sent=1,
            nsessions=1,
            cold_start_candidate_guardrails_enabled=True,
        )
    )

    assert _ids(result.selected) == [101]
    assert retriever.calls[0]["engine"] == "cold_start_explore"
    assert retriever.calls[0]["kwargs"] == {"candidate_guardrails_enabled": True}
    assert result.diagnostics.cold_start_candidate_guardrails_enabled is True
    assert result.diagnostics.cold_start_candidate_guardrails_applied is True


@pytest.mark.asyncio
async def test_cold_start_guardrails_keep_first_position_control_in_mixed_batch():
    retriever = FakeRetriever(
        {
            "cold_start_explore": [
                _meme(101, "cold_start_explore"),
                _meme(102, "cold_start_explore_guarded"),
            ]
        }
    )

    result = await _pipeline(retriever).run(
        _request(
            nmemes_sent=0,
            nsessions=1,
            cold_start_candidate_guardrails_enabled=True,
        )
    )

    assert _ids(result.selected) == [101, 102]
    assert retriever.calls[0]["kwargs"] == {}
    assert retriever.calls[1]["kwargs"] == {"candidate_guardrails_enabled": True}
    assert result.diagnostics.cold_start_candidate_guardrails_applied is True


@pytest.mark.asyncio
async def test_cold_start_guardrails_preserve_existing_fallbacks():
    retriever = FakeRetriever(
        {
            "cold_start_adapt": [],
            "text_light_lr_smoothed": [_meme(301, "text_light_lr_smoothed")],
            "best_uploaded_memes": [_meme(401, "best_uploaded_memes")],
        }
    )

    result = await _pipeline(retriever).run(
        _request(
            nmemes_sent=8,
            nsessions=1,
            cold_start_candidate_guardrails_enabled=True,
        )
    )

    assert _ids(result.selected) == [301]
    assert [call["engine"] for call in retriever.calls] == [
        "cold_start_adapt",
        "text_light_lr_smoothed",
    ]
    assert retriever.calls[0]["kwargs"] == {"candidate_guardrails_enabled": True}
    assert retriever.calls[1]["kwargs"] == {"min_sends": 10}
    assert result.diagnostics.fallback_used == "text_light_lr_smoothed"


@pytest.mark.asyncio
async def test_cold_start_guardrails_do_not_apply_to_dormant_or_mature_users():
    dormant_retriever = FakeRetriever(
        {
            "lr_smoothed": [_meme(101, "lr_smoothed")],
            "recently_liked": [_meme(102, "recently_liked")],
        }
    )

    dormant_result = await _pipeline(dormant_retriever).run(
        _request(
            nmemes_sent=8,
            nsessions=3,
            cold_start_nsessions_gate_enabled=True,
            cold_start_candidate_guardrails_enabled=True,
        )
    )

    assert _ids(dormant_result.selected) == [101, 102]
    assert all(call["kwargs"] == {} for call in dormant_retriever.calls)
    assert dormant_result.diagnostics.cold_start_candidate_guardrails_applied is False

    mature_retriever = FakeRetriever(
        {
            "lr_smoothed": [_meme(201, "lr_smoothed")],
            "recently_liked": [_meme(202, "recently_liked")],
        }
    )

    mature_result = await _pipeline(mature_retriever).run(
        _request(
            nmemes_sent=50,
            nsessions=5,
            cold_start_candidate_guardrails_enabled=True,
        )
    )

    assert _ids(mature_result.selected) == [201, 202]
    assert all(call["kwargs"] == {} for call in mature_retriever.calls)
    assert mature_result.diagnostics.cold_start_candidate_guardrails_applied is False


@pytest.mark.asyncio
async def test_blend_engine_failure_is_recorded_but_other_engines_continue():
    retriever = FakeRetriever(
        {
            "lr_smoothed": [_meme(101, "lr_smoothed")],
            "recently_liked": [_meme(102, "recently_liked")],
            "goat": [_meme(103, "goat")],
        },
        failing_engines={"goat"},
    )

    result = await _pipeline(retriever).run(_request(nmemes_sent=50))

    assert _ids(result.selected) == [101, 102]
    assert "goat" in repr(result.diagnostics)
    assert "temporarily unavailable" in repr(result.diagnostics)


@pytest.mark.asyncio
async def test_moderator_low_sent_candidates_are_prepended():
    async def low_sent_fetcher(
        request: RecommendationBatchRequest,
        limit: int,
        exclude_meme_ids: list[int],
    ) -> list[dict[str, Any]]:
        del request, limit, exclude_meme_ids
        return [
            _meme(901, "low_sent_pool"),
            _meme(902, "low_sent_pool"),
        ]

    retriever = FakeRetriever(
        {
            "lr_smoothed": [_meme(101, "lr_smoothed")],
            "recently_liked": [_meme(102, "recently_liked")],
        }
    )

    result = await _pipeline(retriever, low_sent_fetcher=low_sent_fetcher).run(
        _request(limit=4, user_type="moderator", nmemes_sent=200)
    )

    assert _ids(result.selected) == [901, 902, 101, 102]


@pytest.mark.asyncio
async def test_source_diversity_is_disabled_by_default():
    retriever = FakeRetriever(
        {
            "lr_smoothed": [
                _meme(101, "lr_smoothed", meme_source_id=1),
                _meme(102, "lr_smoothed", meme_source_id=1),
                _meme(103, "lr_smoothed", meme_source_id=2),
            ]
        }
    )

    result = await _pipeline(retriever).run(_request(nmemes_sent=50))

    assert _ids(result.selected) == [101, 102, 103]


@pytest.mark.asyncio
async def test_source_diversity_enabled_reorders_only_when_source_metadata_exists():
    retriever = FakeRetriever(
        {
            "lr_smoothed": [
                _meme(101, "lr_smoothed", meme_source_id=1),
                _meme(102, "lr_smoothed", meme_source_id=1),
                _meme(103, "lr_smoothed", meme_source_id=2),
                _meme(104, "lr_smoothed", meme_source_id=1),
            ]
        }
    )

    with_source_metadata = await _pipeline(retriever).run(
        _request(nmemes_sent=50, source_diversity_enabled=True)
    )

    assert _ids(with_source_metadata.selected) == [101, 103, 102, 104]

    retriever_without_metadata = FakeRetriever(
        {
            "lr_smoothed": [
                _meme(201, "lr_smoothed"),
                _meme(202, "lr_smoothed"),
                _meme(203, "lr_smoothed"),
            ]
        }
    )

    without_source_metadata = await _pipeline(retriever_without_metadata).run(
        _request(nmemes_sent=50, source_diversity_enabled=True)
    )

    assert _ids(without_source_metadata.selected) == [201, 202, 203]


@pytest.mark.asyncio
async def test_shadow_scoring_records_summary_without_changing_selected_order():
    async def shadow_scorer(
        candidates: list[dict[str, Any]],
        request: RecommendationBatchRequest,
    ) -> dict[str, Any]:
        del request
        return {
            "summary": {
                "candidate_count": len(candidates),
                "top_shadow_id": 103,
            },
            "scores": {
                101: 0.1,
                102: 0.5,
                103: 0.9,
            },
        }

    retriever = FakeRetriever(
        {
            "lr_smoothed": [
                _meme(101, "lr_smoothed"),
                _meme(102, "lr_smoothed"),
                _meme(103, "lr_smoothed"),
            ]
        }
    )

    result = await _pipeline(retriever, shadow_scorer=shadow_scorer).run(
        _request(nmemes_sent=50, shadow_scoring_enabled=True)
    )

    assert _ids(result.selected) == [101, 102, 103]
    assert result.diagnostics.shadow_scoring_payload == {
        "summary": {
            "candidate_count": 3,
            "top_shadow_id": 103,
        },
        "scores": {
            101: 0.1,
            102: 0.5,
            103: 0.9,
        },
    }


@pytest.mark.asyncio
async def test_compact_diagnostics_exclude_candidate_ids():
    retriever = FakeRetriever(
        {
            "lr_smoothed": [
                _meme(101, "lr_smoothed"),
                _meme(102, "lr_smoothed"),
            ]
        }
    )

    result = await _pipeline(retriever).run(_request(nmemes_sent=50))

    compact_json = json.dumps(result.diagnostics.compact(), sort_keys=True)
    assert "selected_ids" not in compact_json
    assert "candidate_ids" not in compact_json
    assert result.diagnostics.full()["selected_ids"] == [101, 102]
