from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Awaitable, Callable, Mapping, Sequence

from sqlalchemy import text

from src.feed_turn.planner import (
    COLD_START_1,
    COLD_START_2,
    MATURE,
    CandidateSelectionPlan,
    low_sent_quota,
    plan_candidate_selection_for_user,
)
from src.observability.sentry import sentry_log_extra
from src.recommendations.blender import blend as default_blend
from src.recommendations.candidates import CandidatesRetriever
from src.recommendations.utils import (
    disliked_source_demote_sql,
    exclude_meme_ids_sql_filter,
)

logger = logging.getLogger(__name__)

LOW_SENT_POOL_MIN_REACTIONS_FOR_QUALITY_GATE = 10
LOW_SENT_POOL_MIN_LIKE_RATE = 0.15
# explore_budget_v1 labeling budget: low_sent only serves fresh, still-unlabeled
# memes and stops early on clear losers.
EXPLORE_BUDGET_LOW_SENT_MAX_AGE_DAYS = 7
EXPLORE_BUDGET_LOW_SENT_MAX_REACTIONS = 20
EXPLORE_BUDGET_LOW_SENT_MIN_SMOOTHED_LR = 0.25
# Fresh memes whose first >= 20 reactions are < 40% likes (prod: later LR 0.355).
BAD_FRESH_MAX_AGE_DAYS = 7
BAD_FRESH_MIN_REACTIONS = 20
BAD_FRESH_MAX_LIKE_RATE = 0.40
FRESH_VIRAL_BLEND_SHARE = 0.15

Candidate = dict[str, Any]
BlendFunc = Callable[
    [
        dict[str, list[Candidate]],
        Mapping[str, float],
        Mapping[int, str] | None,
        int,
        int | None,
    ],
    list[Candidate],
]
FetchAllFunc = Callable[[Any, Mapping[str, Any] | None], Awaitable[list[Candidate]]]
LowSentFetcher = Callable[
    ["RecommendationBatchRequest", int, list[int]], Awaitable[list[Candidate]]
]
SwallowWarning = tuple[str, tuple[Any, ...]]


@dataclass(frozen=True)
class RecommendationBatchRequest:
    user_id: int
    limit: int
    nmemes_sent: int
    nsessions: int = 0
    account_age_days: int | None = None
    cold_start_account_too_old: bool = False
    user_type: str | None = None
    meme_ids_in_queue: Sequence[int] = field(default_factory=tuple)
    random_seed: int | None = None
    cold_start_nsessions_gate_enabled: bool = False
    cold_start_candidate_guardrails_enabled: bool = False
    explore_budget_enabled: bool = False


@dataclass(frozen=True)
class EngineRunDiagnostics:
    engine: str
    duration_ms: int
    candidate_count: int
    kwargs_keys: tuple[str, ...] = ()
    error_type: str | None = None

    def compact(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "duration_ms": self.duration_ms,
            "candidate_count": self.candidate_count,
            "kwargs_keys": list(self.kwargs_keys),
            "error_type": self.error_type,
        }


@dataclass
class RecommendationBatchDiagnostics:
    batch_id: str
    user_id: int
    limit: int
    nmemes_sent: int
    nsessions: int
    account_age_days: int | None
    cold_start_account_too_old: bool
    user_type: str | None
    queue_len_before: int
    exclude_count: int
    cold_start_nsessions_gate_enabled: bool = False
    cold_start_candidate_guardrails_enabled: bool = False
    cold_start_candidate_guardrails_applied: bool = False
    maturity_stage: str | None = None
    duration_ms: int = 0
    selected_count: int = 0
    enqueued_count: int = 0
    low_sent_count: int = 0
    fallback_used: str | None = None
    last_resort_used: bool = False
    outcome: str = "success"
    error_type: str | None = None
    engine_runs: list[EngineRunDiagnostics] = field(default_factory=list)

    @property
    def engine_count(self) -> int:
        return len(self.engine_runs)

    @property
    def engine_error_count(self) -> int:
        return sum(1 for run in self.engine_runs if run.error_type)

    @property
    def engine_empty_count(self) -> int:
        return sum(
            1 for run in self.engine_runs if run.error_type is None and run.candidate_count == 0
        )

    def compact(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "maturity_stage": self.maturity_stage,
            "user_type": self.user_type,
            "limit": self.limit,
            "nmemes_sent": self.nmemes_sent,
            "nsessions": self.nsessions,
            "account_age_days": self.account_age_days,
            "cold_start_account_too_old": self.cold_start_account_too_old,
            "cold_start_nsessions_gate_enabled": self.cold_start_nsessions_gate_enabled,
            "cold_start_candidate_guardrails_enabled": (
                self.cold_start_candidate_guardrails_enabled
            ),
            "cold_start_candidate_guardrails_applied": (
                self.cold_start_candidate_guardrails_applied
            ),
            "queue_len_before": self.queue_len_before,
            "exclude_count": self.exclude_count,
            "selected_count": self.selected_count,
            "enqueued_count": self.enqueued_count,
            "duration_ms": self.duration_ms,
            "engine_count": self.engine_count,
            "engine_error_count": self.engine_error_count,
            "engine_empty_count": self.engine_empty_count,
            "low_sent_count": self.low_sent_count,
            "fallback_used": self.fallback_used,
            "last_resort_used": self.last_resort_used,
            "outcome": self.outcome,
            "error_type": self.error_type,
        }


@dataclass(frozen=True)
class RecommendationBatchResult:
    selected: list[Candidate]
    diagnostics: RecommendationBatchDiagnostics


def record_recommendation_batch_diagnostics(diagnostics: RecommendationBatchDiagnostics) -> None:
    extra = sentry_log_extra({"recommendation_batch": diagnostics.compact()})
    level = (
        logging.WARNING
        if diagnostics.outcome != "success" or diagnostics.engine_error_count
        else logging.INFO
    )
    logger.log(level, "recommendation batch diagnostics", extra=extra)


class RecommendationBatchPipeline:
    def __init__(
        self,
        *,
        retriever: CandidatesRetriever | None = None,
        blend_func: BlendFunc | None = None,
        fetch_all_func: FetchAllFunc | None = None,
        low_sent_fetcher: LowSentFetcher | None = None,
    ) -> None:
        self.retriever = retriever or CandidatesRetriever()
        self.blend_func = blend_func or default_blend
        self.fetch_all_func = fetch_all_func
        self.low_sent_fetcher = low_sent_fetcher

    async def run(self, request: RecommendationBatchRequest) -> RecommendationBatchResult:
        diagnostics = RecommendationBatchDiagnostics(
            batch_id=str(uuid.uuid4()),
            user_id=request.user_id,
            limit=request.limit,
            nmemes_sent=request.nmemes_sent,
            nsessions=request.nsessions,
            account_age_days=request.account_age_days,
            cold_start_account_too_old=request.cold_start_account_too_old,
            user_type=request.user_type,
            queue_len_before=len(request.meme_ids_in_queue),
            exclude_count=len(request.meme_ids_in_queue),
            cold_start_nsessions_gate_enabled=request.cold_start_nsessions_gate_enabled,
            cold_start_candidate_guardrails_enabled=(
                request.cold_start_candidate_guardrails_enabled
            ),
        )
        started_at = perf_counter()

        try:
            selected = await self._select_batch(request, diagnostics)
        except Exception as error:
            diagnostics.duration_ms = _elapsed_ms(started_at)
            diagnostics.outcome = "failure"
            diagnostics.error_type = type(error).__name__
            record_recommendation_batch_diagnostics(diagnostics)
            raise
        diagnostics.duration_ms = _elapsed_ms(started_at)
        diagnostics.selected_count = len(selected)
        return RecommendationBatchResult(selected=selected, diagnostics=diagnostics)

    async def _select_batch(
        self,
        request: RecommendationBatchRequest,
        diagnostics: RecommendationBatchDiagnostics,
    ) -> list[Candidate]:
        if request.limit <= 0:
            return []

        quota = low_sent_quota(request.limit, request.user_type, request.explore_budget_enabled)
        if quota <= 0:
            return await self._select_by_plan(
                request,
                diagnostics,
                limit=request.limit,
                exclude_ids=list(request.meme_ids_in_queue),
            )

        candidates = await self._get_low_sent_candidates(
            request.user_id,
            quota,
            list(request.meme_ids_in_queue),
            diagnostics,
            explore_budget=request.explore_budget_enabled,
        )
        exclude_ids = list(request.meme_ids_in_queue)
        exclude_ids.extend(_candidate_ids(candidates))

        remaining_limit = max(0, request.limit - len(candidates))
        if remaining_limit > 0:
            planned = await self._select_by_plan(
                request,
                diagnostics,
                limit=remaining_limit,
                exclude_ids=exclude_ids,
            )
            if _is_idle_return(request):
                # The first meme after an idle gap is a proven one, not a label.
                candidates = planned[:1] + candidates + planned[1:]
            else:
                candidates.extend(planned)

        if not candidates:
            candidates = await self._get_last_resort_candidates(
                request.user_id,
                request.limit,
                list(request.meme_ids_in_queue),
                diagnostics,
            )

        return candidates

    async def _select_by_plan(
        self,
        request: RecommendationBatchRequest,
        diagnostics: RecommendationBatchDiagnostics,
        *,
        limit: int,
        exclude_ids: list[int],
    ) -> list[Candidate]:
        if limit <= 0:
            return []

        plan = plan_candidate_selection_for_user(
            nmemes_sent=request.nmemes_sent,
            nsessions=request.nsessions,
            cold_start_nsessions_gate_enabled=request.cold_start_nsessions_gate_enabled,
            limit=limit,
            cold_start_account_too_old=request.cold_start_account_too_old,
            idle_return=_is_idle_return(request),
        )
        diagnostics.maturity_stage = plan.maturity_stage

        if plan.primary_engine:
            candidates = await self._fetch_primary_engine(
                plan.primary_engine,
                request,
                plan,
                diagnostics,
                limit,
                exclude_ids,
            )
            if candidates:
                return candidates
            return await self._run_fallbacks(plan, request, limit, exclude_ids, diagnostics)

        weights = dict(plan.blend_weights)
        if request.explore_budget_enabled and plan.maturity_stage == MATURE:
            weights = with_fresh_viral_weight(weights)
        candidates_dict = await self._fetch_candidates_dict(
            list(weights.keys()),
            request.user_id,
            limit,
            exclude_ids,
            diagnostics,
        )
        if request.explore_budget_enabled:
            candidates_dict = await self._drop_bad_fresh(candidates_dict)
        blended = self.blend_func(
            candidates_dict,
            weights,
            dict(plan.fixed_pos),
            limit,
            request.random_seed,
        )
        if blended:
            return blended

        return await self._run_fallbacks(plan, request, limit, exclude_ids, diagnostics)

    async def _fetch_primary_engine(
        self,
        engine: str,
        request: RecommendationBatchRequest,
        plan: CandidateSelectionPlan,
        diagnostics: RecommendationBatchDiagnostics,
        limit: int,
        exclude_ids: list[int],
    ) -> list[Candidate]:
        selected: list[Candidate] = []
        segment_exclude_ids = list(exclude_ids)
        segments = self._primary_engine_fetch_segments(
            engine,
            request,
            plan,
            limit,
            diagnostics,
            queued_or_selected_ahead=len(exclude_ids),
        )

        for segment_limit, kwargs in segments:
            if segment_limit <= 0:
                continue

            candidates = await self._fetch_engine(
                engine,
                request.user_id,
                segment_limit,
                segment_exclude_ids,
                diagnostics,
                **kwargs,
            )
            excluded = set(segment_exclude_ids)
            candidates = [
                candidate for candidate in candidates if candidate.get("id") not in excluded
            ]
            if candidates:
                selected.extend(candidates)
                segment_exclude_ids.extend(_candidate_ids(candidates))
                if (
                    not kwargs.get("candidate_guardrails_enabled")
                    or len(candidates) >= segment_limit
                ):
                    continue

            if kwargs.get("candidate_guardrails_enabled"):
                fallback_limit = max(0, limit - len(selected))
                if fallback_limit > 0:
                    selected.extend(
                        await self._run_fallbacks(
                            plan,
                            request,
                            fallback_limit,
                            segment_exclude_ids,
                            diagnostics,
                        )
                    )
                return selected

        return selected

    def _primary_engine_fetch_segments(
        self,
        engine: str,
        request: RecommendationBatchRequest,
        plan: CandidateSelectionPlan,
        limit: int,
        diagnostics: RecommendationBatchDiagnostics,
        *,
        queued_or_selected_ahead: int,
    ) -> list[tuple[int, dict[str, Any]]]:
        default_segments = [(limit, {})]
        if engine not in {"cold_start_explore", "cold_start_adapt"}:
            return default_segments
        if not request.cold_start_candidate_guardrails_enabled:
            return default_segments
        if plan.maturity_stage not in {COLD_START_1, COLD_START_2}:
            return default_segments
        if (request.nsessions or 0) > 1 or request.cold_start_account_too_old:
            return default_segments

        first_position = request.nmemes_sent + queued_or_selected_ahead + 1
        last_position = request.nmemes_sent + queued_or_selected_ahead + limit
        guarded_start = max(first_position, 2)
        guarded_end = min(last_position, 10)
        if guarded_start > guarded_end:
            return default_segments

        diagnostics.cold_start_candidate_guardrails_applied = True
        segments: list[tuple[int, dict[str, Any]]] = []
        if guarded_start > first_position:
            segments.append((guarded_start - first_position, {}))
        segments.append((guarded_end - guarded_start + 1, {"candidate_guardrails_enabled": True}))
        if last_position > guarded_end:
            segments.append((last_position - guarded_end, {}))
        return segments

    async def _run_fallbacks(
        self,
        plan: CandidateSelectionPlan,
        request: RecommendationBatchRequest,
        limit: int,
        exclude_ids: list[int],
        diagnostics: RecommendationBatchDiagnostics,
    ) -> list[Candidate]:
        for fallback in plan.fallback_engines:
            if not self._retriever_supports_engine(fallback.engine):
                continue
            candidates = await self._fetch_engine(
                fallback.engine,
                request.user_id,
                limit,
                exclude_ids,
                diagnostics,
                **dict(fallback.kwargs),
            )
            if candidates:
                diagnostics.fallback_used = fallback.engine
                return candidates
        return []

    def _retriever_supports_engine(self, engine: str) -> bool:
        engine_map = getattr(self.retriever, "engine_map", None)
        if engine_map is None:
            return True
        if type(self.retriever).get_candidates is not CandidatesRetriever.get_candidates:
            return True
        return engine in engine_map

    async def _fetch_candidates_dict(
        self,
        engines: list[str],
        user_id: int,
        limit: int,
        exclude_ids: list[int],
        diagnostics: RecommendationBatchDiagnostics,
    ) -> dict[str, list[Candidate]]:
        tasks = {
            engine: self._fetch_engine(
                engine,
                user_id,
                limit,
                exclude_ids,
                diagnostics,
                swallow_errors=True,
            )
            for engine in engines
        }
        results = await asyncio.gather(*tasks.values())
        return dict(zip(tasks.keys(), results))

    async def _fetch_engine(
        self,
        engine: str,
        user_id: int,
        limit: int,
        exclude_ids: list[int],
        diagnostics: RecommendationBatchDiagnostics,
        *,
        swallow_errors: bool = False,
        **kwargs: Any,
    ) -> list[Candidate]:
        return await self._fetch_with_diagnostics(
            engine,
            diagnostics,
            self.retriever.get_candidates(
                engine,
                user_id,
                limit,
                exclude_mem_ids=exclude_ids,
                **kwargs,
            ),
            kwargs_keys=tuple(sorted(kwargs.keys())),
            swallow_errors=swallow_errors,
            swallow_warning=(
                "recommendation engine %s failed for user %d",
                (engine, user_id),
            ),
        )

    async def _fetch_with_diagnostics(
        self,
        source_name: str,
        diagnostics: RecommendationBatchDiagnostics,
        candidates_awaitable: Awaitable[list[Candidate]],
        *,
        kwargs_keys: tuple[str, ...] = (),
        swallow_errors: bool = False,
        swallow_warning: SwallowWarning | None = None,
    ) -> list[Candidate]:
        started_at = perf_counter()
        try:
            candidates = await candidates_awaitable
        except Exception as error:
            _record_engine_run(
                diagnostics,
                source_name,
                _elapsed_ms(started_at),
                [],
                kwargs_keys=kwargs_keys,
                error=error,
            )
            if swallow_errors:
                if swallow_warning is None:
                    logger.warning("%s failed", source_name, exc_info=True)
                else:
                    message, args = swallow_warning
                    logger.warning(message, *args, exc_info=True)
                return []
            raise

        _record_engine_run(
            diagnostics,
            source_name,
            _elapsed_ms(started_at),
            candidates,
            kwargs_keys=kwargs_keys,
        )
        return candidates

    async def _drop_bad_fresh(
        self,
        candidates_dict: dict[str, list[Candidate]],
    ) -> dict[str, list[Candidate]]:
        meme_ids = sorted(
            {c["id"] for cs in candidates_dict.values() for c in cs if isinstance(c.get("id"), int)}
        )
        if not meme_ids or self.fetch_all_func is None:
            return candidates_dict

        try:
            bad_rows = await self.fetch_all_func(text(_BAD_FRESH_QUERY), {"meme_ids": meme_ids})
        except Exception:
            logger.warning("bad-fresh filter failed; serving unfiltered blend", exc_info=True)
            return candidates_dict
        bad_ids = {row["id"] for row in bad_rows}
        if not bad_ids:
            return candidates_dict
        return {
            engine: [c for c in candidates if c.get("id") not in bad_ids]
            for engine, candidates in candidates_dict.items()
        }

    async def _get_low_sent_candidates(
        self,
        user_id: int,
        limit: int,
        exclude_ids: list[int],
        diagnostics: RecommendationBatchDiagnostics,
        *,
        explore_budget: bool = False,
    ) -> list[Candidate]:
        if limit <= 0:
            return []

        low_sent_fetcher = self.low_sent_fetcher
        if low_sent_fetcher is not None:
            candidates = await self._fetch_with_diagnostics(
                "low_sent_pool",
                diagnostics,
                low_sent_fetcher(
                    RecommendationBatchRequest(
                        user_id=user_id,
                        limit=limit,
                        nmemes_sent=diagnostics.nmemes_sent,
                        nsessions=diagnostics.nsessions,
                        account_age_days=diagnostics.account_age_days,
                        cold_start_account_too_old=diagnostics.cold_start_account_too_old,
                        user_type=diagnostics.user_type,
                        meme_ids_in_queue=exclude_ids,
                        explore_budget_enabled=explore_budget,
                    ),
                    limit,
                    exclude_ids,
                ),
            )
            diagnostics.low_sent_count = len(candidates)
            return candidates

        candidates = await self._fetch_query_pool(
            "low_sent_pool",
            _low_sent_query(exclude_ids, explore_budget=explore_budget),
            {"user_id": user_id, "limit": limit, **_exclude_params(exclude_ids)},
            diagnostics,
        )
        diagnostics.low_sent_count = len(candidates)
        return candidates

    async def _get_last_resort_candidates(
        self,
        user_id: int,
        limit: int,
        exclude_ids: list[int],
        diagnostics: RecommendationBatchDiagnostics,
    ) -> list[Candidate]:
        candidates = await self._fetch_query_pool(
            "last_resort",
            _last_resort_query(exclude_ids),
            {"user_id": user_id, "limit": limit, **_exclude_params(exclude_ids)},
            diagnostics,
        )
        diagnostics.last_resort_used = bool(candidates)
        if candidates:
            logger.info(
                "Moderator user %s: low_sent + blender empty, last_resort found %d memes",
                user_id,
                len(candidates),
            )
        return candidates

    async def _fetch_query_pool(
        self,
        pool_name: str,
        query: str,
        params: Mapping[str, Any],
        diagnostics: RecommendationBatchDiagnostics,
    ) -> list[Candidate]:
        fetch_all_func = self.fetch_all_func
        if fetch_all_func is None:
            raise RuntimeError("fetch_all_func is required for SQL-backed recommendation pools")

        return await self._fetch_with_diagnostics(
            pool_name,
            diagnostics,
            fetch_all_func(text(query), params),
        )


def _is_idle_return(request: RecommendationBatchRequest) -> bool:
    """Empty queue == the batch's first meme is the next one shown. The Redis
    queue expires 1h after the last refill, so this is the post-push slot."""
    return request.explore_budget_enabled and not request.meme_ids_in_queue


def with_fresh_viral_weight(weights: Mapping[str, float]) -> dict[str, float]:
    """Give fresh_viral FRESH_VIRAL_BLEND_SHARE of total mass, scaling others down."""
    total = sum(weights.values())
    scaled = {engine: weight * (1 - FRESH_VIRAL_BLEND_SHARE) for engine, weight in weights.items()}
    scaled["fresh_viral"] = total * FRESH_VIRAL_BLEND_SHARE
    return scaled


def _low_sent_query(exclude_ids: list[int], explore_budget: bool = False) -> str:
    reactions = "(COALESCE(MS.nlikes, 0) + COALESCE(MS.ndislikes, 0))"
    if explore_budget:
        # Labeling budget: fresh + unlabeled only, early-stop clear losers,
        # and the user's disliked sources go last (same demote as engines).
        pool_filter = f"""
            AND M.created_at >= NOW() - INTERVAL '{EXPLORE_BUDGET_LOW_SENT_MAX_AGE_DAYS} days'
            AND {reactions} < {EXPLORE_BUDGET_LOW_SENT_MAX_REACTIONS}
            AND (
                {reactions} < {LOW_SENT_POOL_MIN_REACTIONS_FOR_QUALITY_GATE}
                OR (COALESCE(MS.nlikes, 0) + 1.) / ({reactions} + 2.)
                    >= {EXPLORE_BUDGET_LOW_SENT_MIN_SMOOTHED_LR}
            )
        """
        source_order = f"{disliked_source_demote_sql()} DESC,"
    else:
        pool_filter = f"""
            AND (
                {reactions} < {LOW_SENT_POOL_MIN_REACTIONS_FOR_QUALITY_GATE}
                OR COALESCE(MS.nlikes, 0)::float / NULLIF({reactions}, 0)
                    >= {LOW_SENT_POOL_MIN_LIKE_RATE}
            )
        """
        source_order = ""
    return f"""
        SELECT
            M.id,
            M.type,
            M.telegram_file_id,
            M.caption,
            'low_sent_pool' AS recommended_by,
            COALESCE(MS.nlikes, 0) AS nlikes
        FROM meme M
        LEFT JOIN meme_stats MS
            ON MS.meme_id = M.id
        LEFT JOIN user_meme_reaction R
            ON R.user_id = :user_id
            AND R.meme_id = M.id
        INNER JOIN user_language UL
            ON UL.user_id = :user_id
            AND UL.language_code = M.language_code
        LEFT JOIN user_meme_source_stats UMSS
            ON UMSS.meme_source_id = M.meme_source_id
            AND UMSS.user_id = :user_id
        WHERE 1=1
            AND M.status = 'ok'
            AND R.meme_id IS NULL
            {pool_filter}
            {exclude_meme_ids_sql_filter(exclude_ids)}
        ORDER BY
            {source_order}
            {reactions},
            COALESCE(MS.nmemes_sent, 0),
            M.id
        LIMIT :limit
    """


_BAD_FRESH_QUERY = f"""
    SELECT M.id
    FROM meme M
    INNER JOIN meme_stats MS
        ON MS.meme_id = M.id
    WHERE M.id = ANY(:meme_ids)
        AND M.created_at >= NOW() - INTERVAL '{BAD_FRESH_MAX_AGE_DAYS} days'
        AND MS.nlikes + MS.ndislikes >= {BAD_FRESH_MIN_REACTIONS}
        AND MS.nlikes < {BAD_FRESH_MAX_LIKE_RATE} * (MS.nlikes + MS.ndislikes)
"""


def _last_resort_query(exclude_ids: list[int]) -> str:
    return f"""
        SELECT
            M.id,
            M.type,
            M.telegram_file_id,
            M.caption,
            'last_resort' AS recommended_by,
            COALESCE(MS.nlikes, 0) AS nlikes
        FROM meme M
        LEFT JOIN meme_stats MS
            ON MS.meme_id = M.id
        LEFT JOIN user_meme_reaction R
            ON R.user_id = :user_id
            AND R.meme_id = M.id
        INNER JOIN user_language UL
            ON UL.user_id = :user_id
            AND UL.language_code = M.language_code
        WHERE M.status = 'ok'
            AND R.meme_id IS NULL
            {exclude_meme_ids_sql_filter(exclude_ids)}
        ORDER BY M.id DESC
        LIMIT :limit
    """


def _exclude_params(exclude_ids: list[int]) -> dict[str, Any]:
    if not exclude_ids:
        return {}
    return {"exclude_meme_ids": exclude_ids}


def _record_engine_run(
    diagnostics: RecommendationBatchDiagnostics,
    engine: str,
    duration_ms: int,
    candidates: Sequence[Mapping[str, Any]],
    *,
    kwargs_keys: tuple[str, ...] = (),
    error: Exception | None = None,
) -> None:
    diagnostics.engine_runs.append(
        EngineRunDiagnostics(
            engine=engine,
            duration_ms=duration_ms,
            candidate_count=len(candidates),
            kwargs_keys=kwargs_keys,
            error_type=None if error is None else type(error).__name__,
        )
    )


def _candidate_ids(candidates: Sequence[Mapping[str, Any]]) -> tuple[int, ...]:
    ids: list[int] = []
    for candidate in candidates:
        candidate_id = _candidate_id(candidate)
        if isinstance(candidate_id, int):
            ids.append(candidate_id)
    return tuple(ids)


def _candidate_id(candidate: Mapping[str, Any]) -> Any:
    return candidate.get("id")


def _elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)
