import hashlib
import logging
from typing import Any

from sqlalchemy import text

from src.database import fetch_one
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
RECENTLY_LIKED_BLENDER_V2_SAMPLE_GATE_PER_VARIANT = 1000
RECENTLY_LIKED_BLENDER_V2_MATURE_MIN_MEMES_SENT = 100
RECENTLY_LIKED_BLENDER_V2_SKIPPER_MIN_REACTIONS_7D = 50
RECENTLY_LIKED_BLENDER_V2_SKIPPER_MAX_LR_7D = 0.20

MATURE_BLENDER_CONTROL_WEIGHTS = {
    "best_uploaded_memes": 0.3,
    "like_spread_and_recent_memes": 0.3,
    "lr_smoothed": 0.4,
    "recently_liked": 0.2,
    "goat": 0.1,
    "es_ranked": 0.1,
}
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


async def get_recent_7d_lr_assignment_metrics(user_id: int) -> dict[str, Any]:
    """Return enrollment-time 7d LR metrics and mature-user LR quartile."""
    query = text(
        """
        WITH recent_reactions AS MATERIALIZED (
            SELECT
                umr.user_id,
                COUNT(*) FILTER (WHERE umr.reaction_id IN (1, 2)) AS reactions_7d,
                COUNT(*) FILTER (WHERE umr.reaction_id = 1) AS likes_7d
            FROM user_meme_reaction umr
            INNER JOIN user_stats us ON us.user_id = umr.user_id
            WHERE umr.reacted_at >= NOW() - INTERVAL '7 days'
                AND umr.reaction_id IN (1, 2)
                AND us.nmemes_sent >= :mature_min_memes_sent
            GROUP BY umr.user_id
        ),
        ranked AS (
            SELECT
                user_id,
                reactions_7d,
                likes_7d,
                likes_7d::float / NULLIF(reactions_7d, 0) AS lr_7d,
                NTILE(4) OVER (
                    ORDER BY likes_7d::float / NULLIF(reactions_7d, 0)
                ) AS lr_quartile
            FROM recent_reactions
        )
        SELECT
            COALESCE(r.likes_7d, 0) AS likes_7d,
            COALESCE(r.reactions_7d, 0) AS reactions_7d,
            COALESCE(r.lr_7d, 0.0) AS lr_7d,
            COALESCE(r.lr_quartile, 1) AS lr_quartile
        FROM (SELECT CAST(:user_id AS bigint) AS user_id) target
        LEFT JOIN ranked r ON r.user_id = target.user_id
        """
    )
    row = await fetch_one(
        query,
        {
            "user_id": user_id,
            "mature_min_memes_sent": RECENTLY_LIKED_BLENDER_V2_MATURE_MIN_MEMES_SENT,
        },
    )
    if row is None:
        return {
            "likes_7d": 0,
            "reactions_7d": 0,
            "lr_7d": 0.0,
            "lr_quartile": 1,
        }
    return {
        "likes_7d": int(row["likes_7d"] or 0),
        "reactions_7d": int(row["reactions_7d"] or 0),
        "lr_7d": float(row["lr_7d"] or 0.0),
        "lr_quartile": int(row["lr_quartile"] or 1),
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
    return variant, assignment_metadata


async def get_or_assign_recently_liked_blender_v2_variant(user_id: int) -> str:
    assignment = await get_experiment_assignment(
        user_id,
        RECENTLY_LIKED_BLENDER_V2_EXPERIMENT_ID,
    )
    if assignment is not None:
        return assignment["variant"]

    metrics = await get_recent_7d_lr_assignment_metrics(user_id)
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
