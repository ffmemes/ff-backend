import hashlib
import logging
import uuid
from asyncio import sleep
from typing import Any

import orjson
from sqlalchemy import text

from src.database import fetch_one
from src.feed_turn.planner import MATURE_BLEND_WEIGHTS
from src.redis import redis_client
from src.tgbot.service import (
    assign_experiment,
    get_experiment_assignment,
    get_experiment_variant,
)

logger = logging.getLogger(__name__)

RECENTLY_LIKED_BLENDER_V2_EXPERIMENT_ID = "recently_liked_blender_v2"
RECENTLY_LIKED_BLENDER_V2_CONTROL = "control"
RECENTLY_LIKED_BLENDER_V2_TREATMENT = "treatment"
RECENTLY_LIKED_BLENDER_V2_EXCLUDED = "excluded_high_volume_skipper"
RECENTLY_LIKED_BLENDER_V2_ENROLLMENT_FROZEN = True
RECENTLY_LIKED_BLENDER_V2_ENROLLMENT_FROZEN_AT = "2026-07-23T18:05:54Z"
RECENTLY_LIKED_BLENDER_V2_SAMPLE_GATE_PER_VARIANT = 1000
RECENTLY_LIKED_BLENDER_V2_MATURE_MIN_MEMES_SENT = 100
RECENTLY_LIKED_BLENDER_V2_SKIPPER_MIN_REACTIONS_7D = 50
RECENTLY_LIKED_BLENDER_V2_SKIPPER_MAX_LR_7D = 0.20
RECENTLY_LIKED_BLENDER_V2_QUARTILE_BOUNDARIES_CACHE_KEY = (
    "recently_liked_blender_v2:lr_quartile_boundaries"
)
RECENTLY_LIKED_BLENDER_V2_QUARTILE_BOUNDARIES_LOCK_KEY = (
    "recently_liked_blender_v2:lr_quartile_boundaries:lock"
)
RECENTLY_LIKED_BLENDER_V2_QUARTILE_BOUNDARIES_TTL_SECONDS = 15 * 60
RECENTLY_LIKED_BLENDER_V2_QUARTILE_BOUNDARIES_LOCK_SECONDS = 30
TEXT_LIGHT_BLENDER_V1_EXPERIMENT_ID = "text_light_blender_v1"
TEXT_LIGHT_BLENDER_V1_CONTROL = "control"
TEXT_LIGHT_BLENDER_V1_TREATMENT = "treatment_text_light_lr_smoothed"
TEXT_LIGHT_BLENDER_V1_MAX_OCR_WORDS = 30
TEXT_LIGHT_BLENDER_V1_SAMPLE_GATE_PER_VARIANT = 1000

# Control = default mature plan weights (SSOT in feed_turn.planner).
MATURE_BLENDER_CONTROL_WEIGHTS = dict(MATURE_BLEND_WEIGHTS)
MATURE_BLENDER_TREATMENT_WEIGHTS = {
    "best_uploaded_memes": 0.3,
    "like_spread_and_recent_memes": 0.25,
    "lr_smoothed": 0.35,
    "recently_liked": 0.3,
    "goat": 0.1,
    "es_ranked": 0.1,
}


def _variant_for_quartile(user_id: int, lr_quartile: int) -> str:
    key = f"{RECENTLY_LIKED_BLENDER_V2_EXPERIMENT_ID}:{lr_quartile}:{user_id}"
    bucket = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big") % 2
    if bucket == 0:
        return RECENTLY_LIKED_BLENDER_V2_CONTROL
    return RECENTLY_LIKED_BLENDER_V2_TREATMENT


def _weights_for_variant(variant: str) -> dict[str, float]:
    if variant == RECENTLY_LIKED_BLENDER_V2_TREATMENT:
        return dict(MATURE_BLENDER_TREATMENT_WEIGHTS)
    return dict(MATURE_BLENDER_CONTROL_WEIGHTS)


def _text_light_weights(base_weights: dict[str, float]) -> dict[str, float]:
    weights = dict(base_weights)
    lr_weight = weights.pop("lr_smoothed", 0.0)
    weights["text_light_lr_smoothed"] = lr_weight
    return weights


def _text_light_variant_for_user(user_id: int) -> str:
    key = f"{TEXT_LIGHT_BLENDER_V1_EXPERIMENT_ID}:{user_id}"
    bucket = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big") % 2
    if bucket == 0:
        return TEXT_LIGHT_BLENDER_V1_CONTROL
    return TEXT_LIGHT_BLENDER_V1_TREATMENT


def _coerce_lr_quartile_boundaries(raw_boundaries: Any) -> tuple[float, float, float] | None:
    if raw_boundaries is None:
        return None

    if isinstance(raw_boundaries, str):
        raw_boundaries = raw_boundaries.strip("{}").split(",")

    try:
        boundaries = tuple(float(value) for value in raw_boundaries)
    except (TypeError, ValueError):
        logger.warning(
            "invalid recently_liked blender v2 LR quartile boundaries: %r",
            raw_boundaries,
        )
        return None

    if len(boundaries) != 3 or any(value != value for value in boundaries):
        logger.warning(
            "invalid recently_liked blender v2 LR quartile boundaries: %r",
            raw_boundaries,
        )
        return None

    return tuple(max(0.0, min(1.0, value)) for value in boundaries)


def _lr_quartile_from_boundaries(lr_7d: float, boundaries: tuple[float, float, float]) -> int:
    if lr_7d <= boundaries[0]:
        return 1
    if lr_7d <= boundaries[1]:
        return 2
    if lr_7d <= boundaries[2]:
        return 3
    return 4


async def _get_cached_lr_quartile_boundaries() -> tuple[float, float, float] | None:
    try:
        cached = await redis_client.get(RECENTLY_LIKED_BLENDER_V2_QUARTILE_BOUNDARIES_CACHE_KEY)
    except Exception:
        logger.warning(
            "recently_liked blender v2 LR quartile boundary cache read failed",
            exc_info=True,
        )
        return None

    if not cached:
        return None

    try:
        return _coerce_lr_quartile_boundaries(orjson.loads(cached))
    except orjson.JSONDecodeError:
        logger.warning(
            "recently_liked blender v2 LR quartile boundary cache payload is invalid",
            exc_info=True,
        )
        return None


async def _cache_lr_quartile_boundaries(boundaries: tuple[float, float, float]) -> None:
    try:
        await redis_client.set(
            RECENTLY_LIKED_BLENDER_V2_QUARTILE_BOUNDARIES_CACHE_KEY,
            orjson.dumps(boundaries),
            ex=RECENTLY_LIKED_BLENDER_V2_QUARTILE_BOUNDARIES_TTL_SECONDS,
        )
    except Exception:
        logger.warning(
            "recently_liked blender v2 LR quartile boundary cache write failed",
            exc_info=True,
        )


async def _release_lr_quartile_boundaries_lock(token: str) -> None:
    try:
        current = await redis_client.get(RECENTLY_LIKED_BLENDER_V2_QUARTILE_BOUNDARIES_LOCK_KEY)
        if current == token:
            await redis_client.delete(RECENTLY_LIKED_BLENDER_V2_QUARTILE_BOUNDARIES_LOCK_KEY)
    except Exception:
        logger.warning(
            "recently_liked blender v2 LR quartile boundary lock release failed",
            exc_info=True,
        )


async def _calculate_recent_7d_lr_quartile_boundaries() -> tuple[float, float, float] | None:
    query = text(
        """
        WITH recent_user_lr AS (
            SELECT
                COUNT(*) FILTER (WHERE umr.reaction_id = 1)::float
                    / NULLIF(COUNT(*), 0) AS lr_7d
            FROM user_meme_reaction umr
            INNER JOIN user_stats us ON us.user_id = umr.user_id
            WHERE umr.reacted_at >= NOW() - INTERVAL '7 days'
                AND umr.reaction_id IN (1, 2)
                AND us.nmemes_sent >= :mature_min_memes_sent
            GROUP BY umr.user_id
            HAVING COUNT(*) > 0
        )
        SELECT
            PERCENTILE_CONT(ARRAY[0.25, 0.5, 0.75])
                WITHIN GROUP (ORDER BY lr_7d) AS lr_boundaries
        FROM recent_user_lr
        """
    )
    row = await fetch_one(
        query,
        {"mature_min_memes_sent": RECENTLY_LIKED_BLENDER_V2_MATURE_MIN_MEMES_SENT},
    )
    return _coerce_lr_quartile_boundaries(row["lr_boundaries"] if row else None)


async def get_recent_7d_lr_quartile_boundaries() -> tuple[float, float, float] | None:
    """Return cached mature-user 7d LR quartile cut points.

    Assignment is on the user-facing queue path, so only the lock holder performs
    the global mature-user aggregate. Other workers wait briefly for the cache,
    then skip enrollment until real cut points are cached rather than
    stampeding the DB or assigning users against fallback boundaries.
    """
    cached = await _get_cached_lr_quartile_boundaries()
    if cached is not None:
        return cached

    token = str(uuid.uuid4())
    try:
        acquired = await redis_client.set(
            RECENTLY_LIKED_BLENDER_V2_QUARTILE_BOUNDARIES_LOCK_KEY,
            token,
            nx=True,
            ex=RECENTLY_LIKED_BLENDER_V2_QUARTILE_BOUNDARIES_LOCK_SECONDS,
        )
    except Exception:
        logger.warning(
            "recently_liked blender v2 LR quartile boundary lock failed",
            exc_info=True,
        )
        return None

    if acquired:
        try:
            boundaries = await _calculate_recent_7d_lr_quartile_boundaries()
            if boundaries is not None:
                await _cache_lr_quartile_boundaries(boundaries)
            return boundaries
        finally:
            await _release_lr_quartile_boundaries_lock(token)

    for _ in range(10):
        await sleep(0.1)
        cached = await _get_cached_lr_quartile_boundaries()
        if cached is not None:
            return cached

    logger.warning("recently_liked blender v2 LR quartile boundaries still uncached after waiting")
    return None


async def get_recent_7d_lr_assignment_metrics(user_id: int) -> dict[str, Any] | None:
    """Return enrollment-time 7d LR metrics and mature-user LR quartile."""
    boundaries = await get_recent_7d_lr_quartile_boundaries()
    if boundaries is None:
        return None

    query = text(
        """
        SELECT
            COUNT(*) FILTER (WHERE umr.reaction_id = 1) AS likes_7d,
            COUNT(*) AS reactions_7d,
            COALESCE(
                COUNT(*) FILTER (WHERE umr.reaction_id = 1)::float / NULLIF(COUNT(*), 0),
                0.0
            ) AS lr_7d
        FROM user_meme_reaction umr
        WHERE umr.user_id = :user_id
            AND umr.reacted_at >= NOW() - INTERVAL '7 days'
            AND umr.reaction_id IN (1, 2)
        """
    )
    row = await fetch_one(query, {"user_id": user_id})
    if row is None:
        return {
            "likes_7d": 0,
            "reactions_7d": 0,
            "lr_7d": 0.0,
            "lr_quartile": 1,
            "lr_quartile_boundaries": list(boundaries),
        }
    lr_7d = float(row["lr_7d"] or 0.0)
    return {
        "likes_7d": int(row["likes_7d"] or 0),
        "reactions_7d": int(row["reactions_7d"] or 0),
        "lr_7d": lr_7d,
        "lr_quartile": _lr_quartile_from_boundaries(lr_7d, boundaries),
        "lr_quartile_boundaries": list(boundaries),
    }


def build_recently_liked_blender_v2_assignment(
    user_id: int,
    metrics: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    lr_7d = float(metrics["lr_7d"])
    reactions_7d = int(metrics["reactions_7d"])
    lr_quartile = int(metrics["lr_quartile"])
    high_volume_skipper = (
        reactions_7d > RECENTLY_LIKED_BLENDER_V2_SKIPPER_MIN_REACTIONS_7D
        and lr_7d < RECENTLY_LIKED_BLENDER_V2_SKIPPER_MAX_LR_7D
    )

    if high_volume_skipper:
        variant = RECENTLY_LIKED_BLENDER_V2_EXCLUDED
        excluded_reason = "lr_7d_below_20pct_and_reactions_7d_above_50"
    else:
        variant = _variant_for_quartile(user_id, lr_quartile)
        excluded_reason = None

    assignment_metadata = {
        "assignment_strategy": "sha256(experiment_id:lr_quartile:user_id)%2",
        "lr_quartile": lr_quartile,
        "likes_7d": int(metrics["likes_7d"]),
        "reactions_7d": reactions_7d,
        "lr_7d": round(lr_7d, 6),
        "high_volume_skipper": high_volume_skipper,
        "excluded_reason": excluded_reason,
        "sample_gate_per_variant": RECENTLY_LIKED_BLENDER_V2_SAMPLE_GATE_PER_VARIANT,
        "day3_guardrail": {
            "checkpoint": "rollout_time_plus_3_days",
            "failure_lr_delta_pp": -4,
            "primary_read_rule": "sample_gate_per_variant",
        },
        "assigned_weights": _weights_for_variant(variant),
    }
    if "lr_quartile_boundaries" in metrics:
        assignment_metadata["lr_quartile_boundaries"] = [
            round(float(boundary), 6) for boundary in metrics["lr_quartile_boundaries"]
        ]
    return variant, assignment_metadata


async def get_or_assign_recently_liked_blender_v2_variant(user_id: int) -> str:
    assignment = await get_experiment_assignment(
        user_id,
        RECENTLY_LIKED_BLENDER_V2_EXPERIMENT_ID,
    )
    if assignment is not None:
        return assignment["variant"]

    if RECENTLY_LIKED_BLENDER_V2_ENROLLMENT_FROZEN:
        return RECENTLY_LIKED_BLENDER_V2_CONTROL

    metrics = await get_recent_7d_lr_assignment_metrics(user_id)
    if metrics is None:
        return RECENTLY_LIKED_BLENDER_V2_CONTROL

    proposed_variant, assignment_metadata = build_recently_liked_blender_v2_assignment(
        user_id,
        metrics,
    )
    inserted = await assign_experiment(
        user_id,
        RECENTLY_LIKED_BLENDER_V2_EXPERIMENT_ID,
        proposed_variant,
        assignment_metadata,
    )
    if inserted:
        return proposed_variant

    return (
        await get_experiment_variant(user_id, RECENTLY_LIKED_BLENDER_V2_EXPERIMENT_ID)
        or RECENTLY_LIKED_BLENDER_V2_CONTROL
    )


async def get_recently_liked_blender_v2_weights(user_id: int) -> dict[str, float]:
    try:
        variant = await get_or_assign_recently_liked_blender_v2_variant(user_id)
    except Exception:
        logger.warning(
            "recently_liked blender v2 assignment failed for user %d",
            user_id,
            exc_info=True,
        )
        return dict(MATURE_BLENDER_CONTROL_WEIGHTS)

    return _weights_for_variant(variant)


def build_text_light_blender_v1_assignment(
    user_id: int,
    base_weights: dict[str, float],
) -> tuple[str, dict[str, Any]]:
    variant = _text_light_variant_for_user(user_id)
    treatment_weights = _text_light_weights(base_weights)
    assignment_metadata = {
        "assignment_strategy": "sha256(experiment_id:user_id)%2",
        "max_ocr_words": TEXT_LIGHT_BLENDER_V1_MAX_OCR_WORDS,
        "filtered_engine": "text_light_lr_smoothed",
        "control_engine": "lr_smoothed",
        "sample_gate_per_variant": TEXT_LIGHT_BLENDER_V1_SAMPLE_GATE_PER_VARIANT,
        "primary_read": "compare post-assignment like_rate, session depth, fast-skip rate",
        "base_weights": dict(base_weights),
        "assigned_weights": (
            treatment_weights if variant == TEXT_LIGHT_BLENDER_V1_TREATMENT else dict(base_weights)
        ),
    }
    return variant, assignment_metadata


async def get_or_assign_text_light_blender_v1_variant(
    user_id: int,
    base_weights: dict[str, float],
) -> str:
    assignment = await get_experiment_assignment(
        user_id,
        TEXT_LIGHT_BLENDER_V1_EXPERIMENT_ID,
    )
    if assignment is not None:
        return assignment["variant"]

    proposed_variant, assignment_metadata = build_text_light_blender_v1_assignment(
        user_id,
        base_weights,
    )
    inserted = await assign_experiment(
        user_id,
        TEXT_LIGHT_BLENDER_V1_EXPERIMENT_ID,
        proposed_variant,
        assignment_metadata,
    )
    if inserted:
        return proposed_variant

    return (
        await get_experiment_variant(user_id, TEXT_LIGHT_BLENDER_V1_EXPERIMENT_ID)
        or TEXT_LIGHT_BLENDER_V1_CONTROL
    )


async def get_text_light_blender_v1_weights(
    user_id: int,
    base_weights: dict[str, float],
) -> dict[str, float]:
    try:
        variant = await get_or_assign_text_light_blender_v1_variant(user_id, base_weights)
    except Exception:
        logger.warning(
            "text-light blender v1 assignment failed for user %d",
            user_id,
            exc_info=True,
        )
        return dict(base_weights)

    if variant == TEXT_LIGHT_BLENDER_V1_TREATMENT:
        return _text_light_weights(base_weights)
    return dict(base_weights)
