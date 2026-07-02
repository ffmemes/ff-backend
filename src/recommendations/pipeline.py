from __future__ import annotations

import asyncio
import json
import logging
import random
import uuid
from contextlib import nullcontext
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Awaitable, Callable, Mapping, Sequence

from sqlalchemy import text

from src.config import settings
from src.feed_turn.planner import (
    MATURE,
    CandidateSelectionPlan,
    low_sent_quota,
    plan_candidate_selection_for_user,
)
from src.observability.sentry import sentry_log_extra
from src.recommendations.blender import blend as default_blend
from src.recommendations.blender_experiments import (
    MATURE_BLENDER_CONTROL_WEIGHTS,
    get_recently_liked_blender_v2_weights,
    get_text_light_blender_v1_weights,
)
from src.recommendations.candidates import CandidatesRetriever
from src.recommendations.utils import exclude_meme_ids_sql_filter

try:
    import sentry_sdk
except Exception:  # pragma: no cover - sentry is optional in local tooling
    sentry_sdk = None


logger = logging.getLogger(__name__)

LOW_SENT_POOL_MIN_REACTIONS_FOR_QUALITY_GATE = 10
LOW_SENT_POOL_MIN_LIKE_RATE = 0.15

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
MatureWeightsFunc = Callable[[int], Awaitable[Mapping[str, float]]]
TextLightWeightsFunc = Callable[[int, dict[str, float]], Awaitable[Mapping[str, float]]]
LowSentFetcher = Callable[
    ["RecommendationBatchRequest", int, list[int]], Awaitable[list[Candidate]]
]
ShadowScorer = Callable[
    [list[Candidate], "RecommendationBatchRequest"],
    Awaitable[Mapping[str, Any]] | Mapping[str, Any],
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
    text_light_blender_v1_enabled: bool = False
    source_diversity_enabled: bool = False
    shadow_scoring_enabled: bool = True
    diagnostics_sample_rate: float = 0.01


@dataclass(frozen=True)
class EngineRunDiagnostics:
    engine: str
    duration_ms: int
    candidate_count: int
    candidate_ids: tuple[int, ...] = ()
    kwargs_keys: tuple[str, ...] = ()
    error_type: str | None = None
    error_message: str | None = None

    def compact(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "duration_ms": self.duration_ms,
            "candidate_count": self.candidate_count,
            "kwargs_keys": list(self.kwargs_keys),
            "error_type": self.error_type,
        }

    def full(self, include_candidate_ids: bool) -> dict[str, Any]:
        payload = self.compact() | {"error_message": self.error_message}
        if include_candidate_ids:
            payload["candidate_ids"] = list(self.candidate_ids)
        return payload


@dataclass(frozen=True)
class ShadowScoreSummary:
    candidate_count: int
    quality_feature_count: int
    virality_feature_count: int
    avg_quality_score: float | None
    avg_virality_score: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_count": self.candidate_count,
            "quality_feature_count": self.quality_feature_count,
            "virality_feature_count": self.virality_feature_count,
            "avg_quality_score": self.avg_quality_score,
            "avg_virality_score": self.avg_virality_score,
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
    diagnostics_sample_rate: float = 0.01
    maturity_stage: str | None = None
    duration_ms: int = 0
    selected_count: int = 0
    enqueued_count: int = 0
    low_sent_count: int = 0
    fallback_used: str | None = None
    last_resort_used: bool = False
    source_diversity_enabled: bool = False
    source_diversity_reordered_count: int = 0
    shadow_scoring_enabled: bool = False
    shadow_score_summary: ShadowScoreSummary | None = None
    shadow_scoring_payload: Mapping[str, Any] | None = None
    outcome: str = "success"
    error_type: str | None = None
    error_message: str | None = None
    selected_ids: tuple[int, ...] = ()
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
            "source_diversity_enabled": self.source_diversity_enabled,
            "source_diversity_reordered_count": self.source_diversity_reordered_count,
            "shadow_scoring_enabled": self.shadow_scoring_enabled,
            "shadow_scored_count": (
                None
                if self.shadow_score_summary is None
                else self.shadow_score_summary.candidate_count
            ),
            "outcome": self.outcome,
            "error_type": self.error_type,
        }

    def full(self, include_candidate_ids: bool = True) -> dict[str, Any]:
        payload = self.compact() | {
            "user_id": self.user_id,
            "error_message": self.error_message,
            "engine_runs": [
                engine_run.full(include_candidate_ids=include_candidate_ids)
                for engine_run in self.engine_runs
            ],
            "shadow_score_summary": (
                None if self.shadow_score_summary is None else self.shadow_score_summary.to_dict()
            ),
            "shadow_scoring_payload": self.shadow_scoring_payload,
        }
        if include_candidate_ids:
            payload["selected_ids"] = list(self.selected_ids)
        return payload

    def should_emit_full(self, sample_rate: float) -> bool:
        if self.outcome != "success" or self.engine_error_count > 0:
            return True
        if settings.ENVIRONMENT.is_testing:
            return True
        return random.random() < max(0.0, min(1.0, sample_rate))


@dataclass(frozen=True)
class RecommendationBatchResult:
    selected: list[Candidate]
    diagnostics: RecommendationBatchDiagnostics


def record_recommendation_batch_diagnostics(
    diagnostics: RecommendationBatchDiagnostics,
    *,
    force_full: bool = False,
) -> None:
    sample_rate = diagnostics.limit and diagnostics.diagnostics_sample_rate
    include_full = force_full or diagnostics.should_emit_full(float(sample_rate or 0.0))
    compact = diagnostics.compact()
    extra = sentry_log_extra({"recommendation_batch": compact}, recommendation_full=include_full)
    if include_full:
        extra["ff_recommendation_batch_full_json"] = json.dumps(
            diagnostics.full(include_candidate_ids=True),
            default=str,
        )

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
        shadow_scorer: ShadowScorer | None = None,
        mature_weights_func: MatureWeightsFunc = get_recently_liked_blender_v2_weights,
        text_light_weights_func: TextLightWeightsFunc = get_text_light_blender_v1_weights,
        mature_control_weights: Mapping[str, float] = MATURE_BLENDER_CONTROL_WEIGHTS,
    ) -> None:
        self.retriever = retriever or CandidatesRetriever()
        self.blend_func = blend_func or default_blend
        self.fetch_all_func = fetch_all_func
        self.low_sent_fetcher = low_sent_fetcher
        self.shadow_scorer = shadow_scorer
        self.mature_weights_func = mature_weights_func
        self.text_light_weights_func = text_light_weights_func
        self.mature_control_weights = dict(mature_control_weights)

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
            diagnostics_sample_rate=request.diagnostics_sample_rate,
            source_diversity_enabled=request.source_diversity_enabled,
            shadow_scoring_enabled=request.shadow_scoring_enabled,
        )
        started_at = perf_counter()

        with _start_sentry_span("recommendations.batch", "RecommendationBatchPipeline.run") as span:
            try:
                selected = await self._select_batch(request, diagnostics)
                if request.source_diversity_enabled:
                    selected, reordered_count = diversify_candidates_by_source(selected)
                    diagnostics.source_diversity_reordered_count = reordered_count

                if request.shadow_scoring_enabled:
                    if self.shadow_scorer is None:
                        diagnostics.shadow_score_summary = summarize_shadow_scores(selected)
                    else:
                        shadow_payload = self.shadow_scorer(selected, request)
                        if hasattr(shadow_payload, "__await__"):
                            shadow_payload = await shadow_payload
                        diagnostics.shadow_scoring_payload = shadow_payload

                diagnostics.duration_ms = _elapsed_ms(started_at)
                diagnostics.selected_count = len(selected)
                diagnostics.selected_ids = _candidate_ids(selected)
                _set_sentry_span_data(span, diagnostics)
                return RecommendationBatchResult(selected=selected, diagnostics=diagnostics)
            except Exception as error:
                diagnostics.duration_ms = _elapsed_ms(started_at)
                diagnostics.outcome = "failure"
                diagnostics.error_type = type(error).__name__
                diagnostics.error_message = _trim(str(error))
                _set_sentry_span_data(span, diagnostics)
                record_recommendation_batch_diagnostics(diagnostics, force_full=True)
                raise

    async def _select_batch(
        self,
        request: RecommendationBatchRequest,
        diagnostics: RecommendationBatchDiagnostics,
    ) -> list[Candidate]:
        if request.limit <= 0:
            return []

        quota = low_sent_quota(request.limit, request.user_type)
        if quota <= 0:
            return await self._select_by_plan(
                request,
                diagnostics,
                limit=request.limit,
                exclude_ids=list(request.meme_ids_in_queue),
                use_recently_liked_blender_v2=True,
                use_text_light_blender_v1=request.text_light_blender_v1_enabled,
            )

        candidates = await self._get_low_sent_candidates(
            request.user_id,
            quota,
            list(request.meme_ids_in_queue),
            diagnostics,
        )
        exclude_ids = list(request.meme_ids_in_queue)
        exclude_ids.extend(_candidate_ids(candidates))

        remaining_limit = max(0, request.limit - len(candidates))
        if remaining_limit > 0:
            candidates.extend(
                await self._select_by_plan(
                    request,
                    diagnostics,
                    limit=remaining_limit,
                    exclude_ids=exclude_ids,
                    use_recently_liked_blender_v2=False,
                    use_text_light_blender_v1=False,
                )
            )

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
        use_recently_liked_blender_v2: bool,
        use_text_light_blender_v1: bool,
    ) -> list[Candidate]:
        if limit <= 0:
            return []

        plan = plan_candidate_selection_for_user(
            nmemes_sent=request.nmemes_sent,
            nsessions=request.nsessions,
            cold_start_nsessions_gate_enabled=request.cold_start_nsessions_gate_enabled,
            limit=limit,
            cold_start_account_too_old=request.cold_start_account_too_old,
        )
        diagnostics.maturity_stage = plan.maturity_stage

        if plan.primary_engine:
            candidates = await self._fetch_engine(
                plan.primary_engine,
                request.user_id,
                limit,
                exclude_ids,
                diagnostics,
            )
            if candidates:
                return candidates
            return await self._run_fallbacks(plan, request, limit, exclude_ids, diagnostics)

        weights = await self._blend_weights(
            plan,
            request.user_id,
            use_recently_liked_blender_v2,
            use_text_light_blender_v1,
        )
        candidates_dict = await self._fetch_candidates_dict(
            list(weights.keys()),
            request.user_id,
            limit,
            exclude_ids,
            diagnostics,
        )
        blended = self.blend_func(
            candidates_dict,
            weights,
            _fixed_pos_for_weights(plan, weights),
            limit,
            request.random_seed,
        )
        if blended:
            return blended

        return await self._run_fallbacks(plan, request, limit, exclude_ids, diagnostics)

    async def _blend_weights(
        self,
        plan: CandidateSelectionPlan,
        user_id: int,
        use_recently_liked_blender_v2: bool,
        use_text_light_blender_v1: bool,
    ) -> dict[str, float]:
        if plan.maturity_stage != MATURE:
            weights = dict(plan.blend_weights)
        elif use_recently_liked_blender_v2:
            weights = dict(await self.mature_weights_func(user_id))
        else:
            weights = dict(self.mature_control_weights)

        if use_text_light_blender_v1 and "lr_smoothed" in weights:
            weights = dict(await self.text_light_weights_func(user_id, weights))

        return weights

    async def _run_fallbacks(
        self,
        plan: CandidateSelectionPlan,
        request: RecommendationBatchRequest,
        limit: int,
        exclude_ids: list[int],
        diagnostics: RecommendationBatchDiagnostics,
    ) -> list[Candidate]:
        for fallback in plan.fallback_engines:
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
            span_op="recommendations.engine",
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
        span_op: str,
        kwargs_keys: tuple[str, ...] = (),
        swallow_errors: bool = False,
        swallow_warning: SwallowWarning | None = None,
    ) -> list[Candidate]:
        started_at = perf_counter()
        with _start_sentry_span(span_op, source_name) as span:
            try:
                candidates = await candidates_awaitable
            except Exception as error:
                duration_ms = _elapsed_ms(started_at)
                _record_engine_run(
                    diagnostics,
                    source_name,
                    duration_ms,
                    [],
                    kwargs_keys=kwargs_keys,
                    error=error,
                )
                _set_engine_span_data(span, source_name, duration_ms, 0, error)
                if swallow_errors:
                    if swallow_warning is None:
                        logger.warning("%s failed", source_name, exc_info=True)
                    else:
                        message, args = swallow_warning
                        logger.warning(message, *args, exc_info=True)
                    return []
                raise

            duration_ms = _elapsed_ms(started_at)
            _record_engine_run(
                diagnostics,
                source_name,
                duration_ms,
                candidates,
                kwargs_keys=kwargs_keys,
            )
            _set_engine_span_data(span, source_name, duration_ms, len(candidates), None)
            return candidates

    async def _get_low_sent_candidates(
        self,
        user_id: int,
        limit: int,
        exclude_ids: list[int],
        diagnostics: RecommendationBatchDiagnostics,
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
                    ),
                    limit,
                    exclude_ids,
                ),
                span_op="recommendations.engine",
            )
            diagnostics.low_sent_count = len(candidates)
            return candidates

        candidates = await self._fetch_query_pool(
            "low_sent_pool",
            _low_sent_query(exclude_ids),
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
            span_op="recommendations.sql_pool",
        )


def diversify_candidates_by_source(candidates: list[Candidate]) -> tuple[list[Candidate], int]:
    if not candidates or all(_source_key(candidate) is None for candidate in candidates):
        return candidates, 0

    seen_sources: set[Any] = set()
    first_pass: list[Candidate] = []
    repeated_sources: list[Candidate] = []
    for candidate in candidates:
        source_key = _source_key(candidate)
        if source_key is None or source_key not in seen_sources:
            first_pass.append(candidate)
            if source_key is not None:
                seen_sources.add(source_key)
            continue
        repeated_sources.append(candidate)

    diversified = first_pass + repeated_sources
    reordered_count = sum(
        1
        for before, after in zip(candidates, diversified)
        if _candidate_id(before) != _candidate_id(after)
    )
    return diversified, reordered_count


def _fixed_pos_for_weights(
    plan: CandidateSelectionPlan,
    weights: Mapping[str, float],
) -> dict[int, str]:
    fixed_pos = dict(plan.fixed_pos)
    for position, engine in list(fixed_pos.items()):
        if engine == "lr_smoothed" and "text_light_lr_smoothed" in weights:
            fixed_pos[position] = "text_light_lr_smoothed"
    return fixed_pos


def summarize_shadow_scores(candidates: Sequence[Candidate]) -> ShadowScoreSummary:
    quality_scores: list[float] = []
    virality_scores: list[float] = []
    for candidate in candidates:
        quality_score = _quality_score(candidate)
        if quality_score is not None:
            quality_scores.append(quality_score)

        virality_score = _virality_score(candidate)
        if virality_score is not None:
            virality_scores.append(virality_score)

    return ShadowScoreSummary(
        candidate_count=len(candidates),
        quality_feature_count=len(quality_scores),
        virality_feature_count=len(virality_scores),
        avg_quality_score=_average(quality_scores),
        avg_virality_score=_average(virality_scores),
    )


def _low_sent_query(exclude_ids: list[int]) -> str:
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
        WHERE 1=1
            AND M.status = 'ok'
            AND R.meme_id IS NULL
            AND (
                COALESCE(MS.nlikes, 0) + COALESCE(MS.ndislikes, 0)
                    < {LOW_SENT_POOL_MIN_REACTIONS_FOR_QUALITY_GATE}
                OR (
                    COALESCE(MS.nlikes, 0)::float
                    / NULLIF(COALESCE(MS.nlikes, 0) + COALESCE(MS.ndislikes, 0), 0)
                ) >= {LOW_SENT_POOL_MIN_LIKE_RATE}
            )
            {exclude_meme_ids_sql_filter(exclude_ids)}
        ORDER BY
            COALESCE(MS.nlikes, 0) + COALESCE(MS.ndislikes, 0),
            COALESCE(MS.nmemes_sent, 0),
            M.id
        LIMIT :limit
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
            candidate_ids=_candidate_ids(candidates),
            kwargs_keys=kwargs_keys,
            error_type=None if error is None else type(error).__name__,
            error_message=None if error is None else _trim(str(error)),
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


def _source_key(candidate: Mapping[str, Any]) -> Any:
    source_key = candidate.get("meme_source_id")
    if source_key is not None:
        return source_key
    return candidate.get("source_id")


def _quality_score(candidate: Mapping[str, Any]) -> float | None:
    score = _first_number(candidate, ("lr_smoothed", "engagement_score", "quality_score"))
    if score is not None:
        return score

    nlikes = _first_number(candidate, ("nlikes",))
    ndislikes = _first_number(candidate, ("ndislikes",))
    if nlikes is None and ndislikes is None:
        return None

    likes = nlikes or 0.0
    dislikes = ndislikes or 0.0
    return (likes + 1.0) / (likes + dislikes + 2.0)


def _virality_score(candidate: Mapping[str, Any]) -> float | None:
    return _first_number(
        candidate,
        (
            "invited_count",
            "share_clicks",
            "unique_share_clickers",
            "forwards",
            "nshares",
            "platform_shares",
        ),
    )


def _first_number(candidate: Mapping[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = candidate.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def _elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)


def _trim(value: str, limit: int = 300) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _start_sentry_span(op: str, name: str):
    if sentry_sdk is None:
        return nullcontext()
    try:
        return sentry_sdk.start_span(op=op, name=name)
    except Exception:
        return nullcontext()


def _set_sentry_span_data(span: Any, diagnostics: RecommendationBatchDiagnostics) -> None:
    if span is None:
        return
    compact = diagnostics.compact()
    try:
        span.set_tag("ff.module", "recommendations")
        span.set_tag("recommendation.outcome", diagnostics.outcome)
        if diagnostics.maturity_stage:
            span.set_tag("recommendation.maturity_stage", diagnostics.maturity_stage)
        for key, value in compact.items():
            span.set_data(f"recommendation.{key}", value)
    except Exception:
        return


def _set_engine_span_data(
    span: Any,
    engine: str,
    duration_ms: int,
    candidate_count: int,
    error: Exception | None,
) -> None:
    if span is None:
        return
    try:
        span.set_tag("recommendation.engine", engine)
        span.set_data("recommendation.engine.duration_ms", duration_ms)
        span.set_data("recommendation.engine.candidate_count", candidate_count)
        if error:
            span.set_data("recommendation.engine.error_type", type(error).__name__)
    except Exception:
        return
