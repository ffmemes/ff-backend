from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
from types import MappingProxyType
from typing import Any, Mapping

COLD_START_1 = "cold_start_1"
COLD_START_2 = "cold_start_2"
COLD_START_3 = "cold_start_3"
GROWING = "growing"
MATURE = "mature"

MODERATOR_USER_TYPES = frozenset({"moderator", "admin"})


def _empty_str_any_mapping() -> Mapping[str, Any]:
    return MappingProxyType({})


def _empty_str_float_mapping() -> Mapping[str, float]:
    return MappingProxyType({})


def _empty_int_str_mapping() -> Mapping[int, str]:
    return MappingProxyType({})


@dataclass(frozen=True)
class EngineFallback:
    engine: str
    kwargs: Mapping[str, Any] = field(default_factory=_empty_str_any_mapping)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kwargs", MappingProxyType(dict(self.kwargs)))


@dataclass(frozen=True)
class CandidateSelectionPlan:
    maturity_stage: str
    primary_engine: str | None
    blend_weights: Mapping[str, float] = field(default_factory=_empty_str_float_mapping)
    fixed_pos: Mapping[int, str] = field(default_factory=_empty_int_str_mapping)
    fallback_engines: tuple[EngineFallback, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "blend_weights", MappingProxyType(dict(self.blend_weights)))
        object.__setattr__(self, "fixed_pos", MappingProxyType(dict(self.fixed_pos)))
        object.__setattr__(self, "fallback_engines", tuple(self.fallback_engines))


LR_SMOOTHED_COLD_FALLBACK = EngineFallback("lr_smoothed", {"min_sends": 10})
BEST_UPLOADED_FALLBACK = EngineFallback("best_uploaded_memes")


def plan_candidate_selection(nmemes_sent: int) -> CandidateSelectionPlan:
    if nmemes_sent < 6:
        return CandidateSelectionPlan(
            maturity_stage=COLD_START_1,
            primary_engine="cold_start_explore",
            fallback_engines=(LR_SMOOTHED_COLD_FALLBACK, BEST_UPLOADED_FALLBACK),
        )

    if nmemes_sent < 16:
        return CandidateSelectionPlan(
            maturity_stage=COLD_START_2,
            primary_engine="cold_start_adapt",
            fallback_engines=(LR_SMOOTHED_COLD_FALLBACK, BEST_UPLOADED_FALLBACK),
        )

    if nmemes_sent < 30:
        return CandidateSelectionPlan(
            maturity_stage=COLD_START_3,
            primary_engine=None,
            blend_weights={
                "cold_start_adapt": 0.5,
                "lr_smoothed": 0.3,
                "like_spread_and_recent_memes": 0.2,
            },
            fixed_pos={0: "cold_start_adapt"},
            fallback_engines=(
                EngineFallback("cold_start_adapt"),
                LR_SMOOTHED_COLD_FALLBACK,
                BEST_UPLOADED_FALLBACK,
            ),
        )

    if nmemes_sent < 100:
        return CandidateSelectionPlan(
            maturity_stage=GROWING,
            primary_engine=None,
            blend_weights={
                "best_uploaded_memes": 0.1,
                "lr_smoothed": 0.3,
                "recently_liked": 0.2,
                "goat": 0.1,
                "es_ranked": 0.1,
                "like_spread_and_recent_memes": 0.2,
            },
            fixed_pos={0: "lr_smoothed"},
        )

    return CandidateSelectionPlan(
        maturity_stage=MATURE,
        primary_engine=None,
        blend_weights={
            "best_uploaded_memes": 0.3,
            "like_spread_and_recent_memes": 0.3,
            "lr_smoothed": 0.4,
            "recently_liked": 0.2,
            "goat": 0.1,
            "es_ranked": 0.1,
        },
        fixed_pos={0: "lr_smoothed"},
    )


def low_sent_quota(limit: int, user_type: str | None) -> int:
    value = getattr(user_type, "value", user_type)
    if value is None or str(value) not in MODERATOR_USER_TYPES:
        return 0
    return ceil(limit * 0.75)
