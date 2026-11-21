"""High-confidence meme selection for retention broadcasts.

Feed queue pop is optimized for continuous scrolling. Reengagement pushes need
a single strong meme that earns a *fast* reaction when the user returns.
Prefer liked sources + proven like rate; majority-dislike sources are demoted.
"""

from __future__ import annotations

import hashlib
import logging
import math
import random

from sqlalchemy import text

from src.config import settings
from src.database import engine, fetch_one
from src.recommendations.meme_queue import check_queue, get_next_meme_for_user
from src.recommendations.utils import disliked_source_demote_sql
from src.storage.schemas import MemeData

logger = logging.getLogger(__name__)

# Delivery-path labels for analytics (dwell / reactivation).
BROADCAST_RECOMMENDED_BY = "broadcast_reengagement"
BROADCAST_HQ_RECOMMENDED_BY = "broadcast_reengagement_hq"
BROADCAST_EXPLORE_RECOMMENDED_BY = "broadcast_reengagement_explore"

# Quality floors for the HQ pick (explicit reactions, not lr_smoothed alone).
_HQ_MIN_EXPLICIT_REACTIONS = 15
_HQ_MIN_RAW_LIKE_RATE = 0.45


async def pick_reengagement_meme(user_id: int) -> tuple[MemeData | None, str]:
    """Return (meme, recommended_by_label) for a retention push.

    Tries the affinity HQ pick (``broadcast_reengagement_hq``), then the feed
    queue (``broadcast_reengagement``).
    """
    if settings.BROADCAST_HIGH_QUALITY_PICK_ENABLED:
        meme = await _fetch_high_quality_reengagement_meme(user_id)
        if meme is not None:
            return meme, BROADCAST_HQ_RECOMMENDED_BY
        logger.info(
            "broadcast HQ pick empty for user_id=%s; falling back to feed queue",
            user_id,
        )

    await check_queue(user_id)
    meme = await get_next_meme_for_user(user_id)
    if meme is None:
        return None, BROADCAST_RECOMMENDED_BY
    return meme, BROADCAST_RECOMMENDED_BY


async def pick_exploration_meme(
    user_id: int, variant: str, opportunity_id: str
) -> tuple[MemeData | None, str, dict]:
    """Pick once after dispatch has durably reserved this scheduled opportunity.

    Probabilities condition on the recorded, ordered HQ pool. The fallback
    queue generation probability is unknown, so it is explicitly excluded
    from candidate-policy evaluation.
    """
    if variant not in {"hq", "explore"}:
        raise ValueError("variant must be hq or explore")
    if not opportunity_id:
        raise ValueError("opportunity_id must identify the reserved opportunity")

    rows = []
    fallback_reason = "hq_disabled"
    if settings.BROADCAST_HIGH_QUALITY_PICK_ENABLED:
        rows = await _fetch_exploration_candidates(user_id)
        fallback_reason = "hq_empty"
    metadata = {
        "policy_version": "push_hq_top3_v1",
        "candidate_ids": [row["id"] for row in rows],
        "candidate_scores": [_finite_score(row.get("hq_score")) for row in rows],
        "candidate_features": [_candidate_snapshot(row) for row in rows],
        "feature_version": "materialized_hq_totals_v1",
        "source_demote": {
            "enabled": settings.RECOMMENDATION_DEMOTE_DISLIKED_SOURCES,
            "min_reactions": settings.RECOMMENDATION_DEMOTE_DISLIKED_MIN_REACTIONS,
            "multiplier": _finite_score(settings.RECOMMENDATION_DEMOTE_DISLIKED_MULTIPLIER),
        },
        "arm_probability": 0.5,
        "fallback_reason": None,
    }
    if rows:
        seed = hashlib.sha256(f"push_hq_top3_v1:item:{user_id}:{opportunity_id}".encode()).digest()
        chosen_index = random.Random(seed).randrange(len(rows)) if variant == "explore" else 0
        conditional_probability = 1.0 / len(rows) if variant == "explore" else 1.0
        metadata.update(
            language_code=rows[chosen_index].get("language_code"),
            chosen_index=chosen_index,
            selection_probability=conditional_probability,
            joint_probability=0.5 * conditional_probability,
            mixture_probability=(0.5 if chosen_index == 0 else 0.0) + 0.5 / len(rows),
        )
        label = (
            BROADCAST_EXPLORE_RECOMMENDED_BY
            if variant == "explore"
            else BROADCAST_HQ_RECOMMENDED_BY
        )
        return _meme_from_row(rows[chosen_index], label), label, metadata

    # The shared fallback is evaluated once, after the empty pool is recorded.
    await check_queue(user_id)
    meme = await get_next_meme_for_user(user_id)
    metadata.update(
        fallback_reason=fallback_reason,
        chosen_index=None,
        selection_probability=None,
        joint_probability=None,
        mixture_probability=None,
    )
    return meme, BROADCAST_RECOMMENDED_BY, metadata


def _finite_score(value: float | None) -> float | None:
    if value is None:
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite HQ feature")
    return result


def _candidate_snapshot(row: dict) -> dict:
    """Materialized totals observed by this query, with aggregate watermarks.

    These are the current production aggregates, including their existing
    seeding and reaction filters. They differ from offline 35-day feed counts.
    """
    snapshot = {
        field: row.get(field)
        for field in (
            "id",
            "meme_source_id",
            "language_code",
            "type",
            "nlikes",
            "ndislikes",
            "source_nlikes",
            "source_ndislikes",
        )
    }
    snapshot["lr_smoothed"] = _finite_score(row.get("lr_smoothed"))
    for field in ("observed_at", "meme_stats_updated_at", "source_stats_updated_at"):
        value = row.get(field)
        snapshot[field] = value.isoformat() if value is not None else None
    return snapshot


async def _fetch_exploration_candidates(user_id: int) -> list[dict]:
    # Keep the timeout local to this transaction and the experimental HQ query.
    async with engine.begin() as connection:
        await connection.execute(text("SET LOCAL statement_timeout = '4s'"))
        result = await connection.execute(
            text(_high_quality_query(pool=True)), _high_quality_params(user_id)
        )
        return [dict(row) for row in result.mappings().all()]


def _high_quality_params(user_id: int) -> dict:
    return {
        "user_id": user_id,
        "min_reactions": _HQ_MIN_EXPLICIT_REACTIONS,
        "min_raw_like_rate": _HQ_MIN_RAW_LIKE_RATE,
    }


def _high_quality_query(*, pool: bool = False) -> str:
    score = f"""-1
            * COALESCE(
                (UMSS.nlikes + 1.) / (UMSS.nlikes + UMSS.ndislikes + 1.),
                0.5
            )
            * {disliked_source_demote_sql()}
            * (MS.nlikes + 1.) / (MS.nlikes + MS.ndislikes + 1.)
            * COALESCE(MS.lr_smoothed, 0.0)"""
    score_select = (
        f""", {score} AS hq_score
            , M.language_code, M.meme_source_id, MS.ndislikes, MS.lr_smoothed
            , UMSS.nlikes AS source_nlikes, UMSS.ndislikes AS source_ndislikes
            , statement_timestamp() AS observed_at
            , MS.updated_at AS meme_stats_updated_at
            , UMSS.updated_at AS source_stats_updated_at"""
        if pool
        else ""
    )
    order = "hq_score NULLS LAST, M.id" if pool else f"{score} NULLS LAST"
    limit = 3 if pool else 1
    return f"""
        SELECT
            M.id
            , M.type
            , M.telegram_file_id
            , M.caption
            , COALESCE(MS.nlikes, 0) AS nlikes
            {score_select}
        FROM meme M
        INNER JOIN meme_stats MS
            ON MS.meme_id = M.id
        INNER JOIN user_language L
            ON L.language_code = M.language_code
            AND L.user_id = :user_id
        LEFT JOIN user_meme_reaction R
            ON R.meme_id = M.id
            AND R.user_id = :user_id
        LEFT JOIN user_meme_source_stats UMSS
            ON UMSS.meme_source_id = M.meme_source_id
            AND UMSS.user_id = :user_id
        WHERE 1=1
            AND M.status = 'ok'
            AND M.telegram_file_id IS NOT NULL
            AND R.meme_id IS NULL
            AND (MS.nlikes + MS.ndislikes) >= :min_reactions
            AND (MS.nlikes::float / NULLIF(MS.nlikes + MS.ndislikes, 0))
                >= :min_raw_like_rate
        ORDER BY {order}
        LIMIT {limit}
    """


async def _fetch_high_quality_reengagement_meme(user_id: int) -> MemeData | None:
    """Single best unseen meme: user×source affinity × raw like rate × demote."""
    row = await fetch_one(text(_high_quality_query()), _high_quality_params(user_id))
    return _meme_from_row(row, BROADCAST_HQ_RECOMMENDED_BY)


def _meme_from_row(row: dict | None, recommended_by: str) -> MemeData | None:
    if not row:
        return None
    return MemeData(
        id=row["id"],
        type=row["type"],
        telegram_file_id=row["telegram_file_id"],
        caption=row.get("caption"),
        recommended_by=recommended_by,
        nlikes=int(row.get("nlikes") or 0),
    )
