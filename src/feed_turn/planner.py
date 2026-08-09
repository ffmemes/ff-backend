from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from types import MappingProxyType
from typing import Any, Mapping

COLD_START_1 = "cold_start_1"
COLD_START_2 = "cold_start_2"
COLD_START_3 = "cold_start_3"
GROWING = "growing"
MATURE = "mature"

MODERATOR_USER_TYPES = frozenset({"moderator", "admin"})

# Single source of truth for default blend weights. Experiments must import
# these maps rather than re-declaring the control blend.
GROWING_BLEND_WEIGHTS: Mapping[str, float] = MappingProxyType(
    {
        "best_uploaded_memes": 0.1,
        "lr_smoothed": 0.3,
        "recently_liked": 0.2,
        "goat": 0.1,
        "es_ranked": 0.1,
        "like_spread_and_recent_memes": 0.2,
    }
)
# Shipped 2026-08-09 from recently_liked_blender_v2 treatment (see
# docs/analyst/recently-liked-blender-v2-closeout.md). Relative weights;
# blender normalizes.
MATURE_BLEND_WEIGHTS: Mapping[str, float] = MappingProxyType(
    {
        "best_uploaded_memes": 0.3,
        "like_spread_and_recent_memes": 0.25,
        "lr_smoothed": 0.35,
        "recently_liked": 0.3,
        "goat": 0.1,
        "es_ranked": 0.1,
    }
)


_EMPTY_MAPPING: Mapping[Any, Any] = MappingProxyType({})


@dataclass(frozen=True)
class EngineFallback:
    engine: str
    kwargs: Mapping[str, Any] = _EMPTY_MAPPING

    def __post_init__(self) -> None:
        object.__setattr__(self, "kwargs", MappingProxyType(dict(self.kwargs)))


@dataclass(frozen=True)
class CandidateSelectionPlan:
    maturity_stage: str
    primary_engine: str | None
    blend_weights: Mapping[str, float] = _EMPTY_MAPPING
    fixed_pos: Mapping[int, str] = _EMPTY_MAPPING
    fallback_engines: tuple[EngineFallback, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "blend_weights", MappingProxyType(dict(self.blend_weights)))
        object.__setattr__(self, "fixed_pos", MappingProxyType(dict(self.fixed_pos)))
        object.__setattr__(self, "fallback_engines", tuple(self.fallback_engines))


TEXT_LIGHT_LR_SMOOTHED_COLD_FALLBACK = EngineFallback(
    "text_light_lr_smoothed",
    {"min_sends": 10},
)
BEST_UPLOADED_FALLBACK = EngineFallback("best_uploaded_memes")


def plan_candidate_selection(nmemes_sent: int) -> CandidateSelectionPlan:
    if nmemes_sent < 6:
        return CandidateSelectionPlan(
            maturity_stage=COLD_START_1,
            primary_engine="cold_start_explore",
            fallback_engines=(TEXT_LIGHT_LR_SMOOTHED_COLD_FALLBACK, BEST_UPLOADED_FALLBACK),
        )

    if nmemes_sent < 16:
        return CandidateSelectionPlan(
            maturity_stage=COLD_START_2,
            primary_engine="cold_start_adapt",
            fallback_engines=(TEXT_LIGHT_LR_SMOOTHED_COLD_FALLBACK, BEST_UPLOADED_FALLBACK),
        )

    if nmemes_sent < 30:
        # CS3 (memes 16-29): still personalizing. Prefer proven social proof
        # (best_uploaded + text-light) over like_spread virality — early users
        # lack signal for spread engines, and uploads historically hold LR better.
        return CandidateSelectionPlan(
            maturity_stage=COLD_START_3,
            primary_engine=None,
            blend_weights={
                "cold_start_adapt": 0.4,
                "best_uploaded_memes": 0.3,
                "text_light_lr_smoothed": 0.3,
            },
            fixed_pos={0: "cold_start_adapt"},
            fallback_engines=(
                EngineFallback("cold_start_adapt"),
                TEXT_LIGHT_LR_SMOOTHED_COLD_FALLBACK,
                BEST_UPLOADED_FALLBACK,
            ),
        )

    if nmemes_sent < 100:
        return CandidateSelectionPlan(
            maturity_stage=GROWING,
            primary_engine=None,
            blend_weights=GROWING_BLEND_WEIGHTS,
            fixed_pos={0: "lr_smoothed"},
        )

    return CandidateSelectionPlan(
        maturity_stage=MATURE,
        primary_engine=None,
        blend_weights=MATURE_BLEND_WEIGHTS,
        fixed_pos={0: "lr_smoothed"},
    )


def plan_candidate_selection_for_user(
    nmemes_sent: int,
    nsessions: int | None,
    cold_start_nsessions_gate_enabled: bool,
    limit: int | None = None,
    cold_start_account_too_old: bool = False,
) -> CandidateSelectionPlan:
    """Plan candidate selection with the production cold-start session gate.

    ``limit`` is accepted for batch-pipeline call sites that already carry it;
    candidate selection depends on maturity, session count, and account age.
    """
    _ = limit
    dormant_returner = (nsessions or 0) > 1 or cold_start_account_too_old
    if cold_start_nsessions_gate_enabled and dormant_returner and nmemes_sent < 30:
        return plan_candidate_selection(30)

    return plan_candidate_selection(nmemes_sent)


def low_sent_quota(limit: int, user_type: str | None) -> int:
    value = getattr(user_type, "value", user_type)
    if value is None or str(value) not in MODERATOR_USER_TYPES:
        return 0
    return ceil(limit * 0.75)
