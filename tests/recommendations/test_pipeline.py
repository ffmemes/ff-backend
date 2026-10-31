from typing import Any

import pytest

from src.feed_turn.planner import MATURE_BLEND_WEIGHTS
from src.recommendations.candidates import CandidatesRetriever
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


def _pipeline(
    retriever: FakeRetriever,
    *,
    low_sent_fetcher=_empty_low_sent_fetcher,
) -> RecommendationBatchPipeline:
    return RecommendationBatchPipeline(
        retriever=retriever,
        blend_func=_fake_blend,
        low_sent_fetcher=low_sent_fetcher,
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
            limit=1,
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
async def test_cold_start_guardrails_skip_unsupported_injected_fallback_engines():
    calls = []

    async def cold_start_adapt(
        user_id: int,
        limit: int = 10,
        exclude_meme_ids: list[int] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        calls.append({"engine": "cold_start_adapt", "kwargs": kwargs})
        return []

    async def best_uploaded_memes(
        user_id: int,
        limit: int = 10,
        exclude_meme_ids: list[int] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        calls.append({"engine": "best_uploaded_memes", "kwargs": kwargs})
        return [_meme(401, "best_uploaded_memes")]

    class LimitedFallbackRetriever(CandidatesRetriever):
        engine_map = {
            "cold_start_adapt": cold_start_adapt,
            "best_uploaded_memes": best_uploaded_memes,
        }

    result = await _pipeline(LimitedFallbackRetriever()).run(
        _request(
            nmemes_sent=8,
            nsessions=1,
            cold_start_candidate_guardrails_enabled=True,
        )
    )

    assert _ids(result.selected) == [401]
    assert [call["engine"] for call in calls] == [
        "cold_start_adapt",
        "best_uploaded_memes",
    ]
    assert result.diagnostics.fallback_used == "best_uploaded_memes"


@pytest.mark.asyncio
async def test_cold_start_guardrails_use_queued_items_for_true_new_positions():
    retriever = FakeRetriever(
        {
            "cold_start_adapt": [
                _meme(101, "cold_start_adapt"),
                _meme(102, "cold_start_adapt"),
            ]
        }
    )

    result = await _pipeline(retriever).run(
        _request(
            nmemes_sent=7,
            nsessions=1,
            meme_ids_in_queue=list(range(901, 909)),
            cold_start_candidate_guardrails_enabled=True,
        )
    )

    assert _ids(result.selected) == [101, 102]
    assert [call["engine"] for call in retriever.calls] == ["cold_start_adapt"]
    assert retriever.calls[0]["kwargs"] == {}
    assert result.diagnostics.cold_start_candidate_guardrails_applied is False


@pytest.mark.asyncio
async def test_partial_cold_start_guarded_segment_falls_back_before_unguarded_tail():
    retriever = FakeRetriever(
        {
            "cold_start_explore": [
                _meme(101, "cold_start_explore"),
                _meme(102, "cold_start_explore_guarded"),
                _meme(103, "cold_start_explore_guarded"),
                _meme(104, "cold_start_explore_guarded"),
                _meme(105, "cold_start_explore_guarded"),
            ],
            "text_light_lr_smoothed": [
                _meme(301, "text_light_lr_smoothed"),
                _meme(302, "text_light_lr_smoothed"),
            ],
        }
    )

    result = await _pipeline(retriever).run(
        _request(
            limit=12,
            nmemes_sent=0,
            nsessions=1,
            cold_start_candidate_guardrails_enabled=True,
        )
    )

    assert _ids(result.selected) == [101, 102, 103, 104, 105, 301, 302]
    assert [call["engine"] for call in retriever.calls] == [
        "cold_start_explore",
        "cold_start_explore",
        "text_light_lr_smoothed",
    ]
    assert retriever.calls[0]["kwargs"] == {}
    assert retriever.calls[1]["kwargs"] == {"candidate_guardrails_enabled": True}
    assert retriever.calls[2]["kwargs"] == {"min_sends": 10}
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
    assert result.diagnostics.engine_error_count == 1
    assert "goat" in repr(result.diagnostics)
    assert "RuntimeError" in repr(result.diagnostics)


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
async def test_explore_budget_moderator_gets_half_quota_and_proven_first_slot():
    seen: dict[str, Any] = {}

    async def low_sent_fetcher(request, limit, exclude_meme_ids):
        seen["limit"] = limit
        seen["explore_budget"] = request.explore_budget_enabled
        return [_meme(900 + i, "low_sent_pool") for i in range(limit)]

    retriever = FakeRetriever({"lr_smoothed": [_meme(101), _meme(102)]})
    pipeline = _pipeline(retriever, low_sent_fetcher=low_sent_fetcher)

    result = await pipeline.run(
        _request(limit=4, user_type="moderator", nmemes_sent=200, explore_budget_enabled=True)
    )
    # 50% quota; empty queue => first meme comes from the blend, not labeling.
    assert seen == {"limit": 2, "explore_budget": True}
    assert _ids(result.selected) == [101, 900, 901, 102]

    queued = await pipeline.run(
        _request(
            limit=4,
            user_type="moderator",
            nmemes_sent=200,
            explore_budget_enabled=True,
            meme_ids_in_queue=[1],
        )
    )
    assert _ids(queued.selected) == [900, 901, 101, 102]


@pytest.mark.asyncio
async def test_explore_budget_adds_fresh_viral_and_drops_bad_fresh():
    captured: dict[str, Any] = {}

    def blend(candidates_by_engine, weights, fixed_pos=None, limit=0, random_seed=None):
        captured["weights"] = dict(weights)
        captured["fixed_pos"] = dict(fixed_pos or {})
        return _fake_blend(candidates_by_engine, weights, fixed_pos, limit, random_seed)

    async def fetch_all(query, params):
        captured["bad_fresh_ids"] = params["meme_ids"]
        return [{"id": 102}]

    retriever = FakeRetriever(
        {
            "lr_smoothed": [_meme(101), _meme(102)],
            "fresh_viral": [_meme(301, "fresh_viral")],
        }
    )
    pipeline = RecommendationBatchPipeline(
        retriever=retriever,
        blend_func=blend,
        fetch_all_func=fetch_all,
        low_sent_fetcher=_empty_low_sent_fetcher,
    )

    result = await pipeline.run(_request(limit=5, nmemes_sent=200, explore_budget_enabled=True))

    total = sum(MATURE_BLEND_WEIGHTS.values())
    expected = {engine: weight * 0.85 for engine, weight in MATURE_BLEND_WEIGHTS.items()}
    expected["fresh_viral"] = total * 0.15
    assert captured["weights"] == pytest.approx(expected)
    assert captured["fixed_pos"] == {0: "like_spread_and_recent_memes"}
    assert captured["bad_fresh_ids"] == [101, 102, 301]
    assert _ids(result.selected) == [101, 301]


@pytest.mark.asyncio
async def test_explore_budget_control_keeps_current_feed():
    async def fetch_all(query, params):
        raise AssertionError("control must not run the bad-fresh filter")

    retriever = FakeRetriever({"lr_smoothed": [_meme(101)], "fresh_viral": [_meme(301)]})
    pipeline = RecommendationBatchPipeline(
        retriever=retriever,
        blend_func=_fake_blend,
        fetch_all_func=fetch_all,
        low_sent_fetcher=_empty_low_sent_fetcher,
    )

    result = await pipeline.run(_request(limit=5, nmemes_sent=200))

    assert _ids(result.selected) == [101]
    assert "fresh_viral" not in {call["engine"] for call in retriever.calls}
