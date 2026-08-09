"""High-confidence meme selection for retention broadcasts.

Feed queue pop is optimized for continuous scrolling. Reengagement pushes need
a single strong meme that earns a *fast* reaction when the user returns —
prefer liked sources + proven like rate, never majority-dislike sources.
"""

from __future__ import annotations

import logging

from sqlalchemy import text

from src.config import settings
from src.database import fetch_one
from src.recommendations.meme_queue import check_queue, get_next_meme_for_user
from src.recommendations.utils import (
    block_disliked_sources_sql_filter,
    disliked_source_demote_sql,
)
from src.storage.schemas import MemeData

logger = logging.getLogger(__name__)

# Delivery-path labels for analytics (dwell / reactivation).
BROADCAST_RECOMMENDED_BY = "broadcast_reengagement"
BROADCAST_HQ_RECOMMENDED_BY = "broadcast_reengagement_hq"

# Quality floors for the HQ pick (explicit reactions, not lr_smoothed alone).
_HQ_MIN_EXPLICIT_REACTIONS = 15
_HQ_MIN_RAW_LIKE_RATE = 0.45


async def pick_reengagement_meme(user_id: int) -> tuple[MemeData | None, str]:
    """Return (meme, recommended_by_label) for a retention push.

    When ``BROADCAST_HIGH_QUALITY_PICK_ENABLED`` is on, tries an affinity-aware
    SQL pick first (label ``broadcast_reengagement_hq``). Falls back to the
    normal feed queue (label ``broadcast_reengagement``) so we never skip a user
    solely because the HQ pool is empty.
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


async def _fetch_high_quality_reengagement_meme(user_id: int) -> MemeData | None:
    """Single best unseen meme: user×source affinity × raw like rate × demote."""
    query = f"""
        SELECT
            M.id
            , M.type
            , M.telegram_file_id
            , M.caption
            , COALESCE(MS.nlikes, 0) AS nlikes
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
            {block_disliked_sources_sql_filter()}
        ORDER BY -1
            * COALESCE(
                (UMSS.nlikes + 1.) / (UMSS.nlikes + UMSS.ndislikes + 1.),
                0.5
            )
            * {disliked_source_demote_sql()}
            * (MS.nlikes + 1.) / (MS.nlikes + MS.ndislikes + 1.)
            * COALESCE(MS.lr_smoothed, 0.0)
        NULLS LAST
        LIMIT 1
    """
    row = await fetch_one(
        text(query),
        {
            "user_id": user_id,
            "min_reactions": _HQ_MIN_EXPLICIT_REACTIONS,
            "min_raw_like_rate": _HQ_MIN_RAW_LIKE_RATE,
        },
    )
    if not row:
        return None
    return MemeData(
        id=row["id"],
        type=row["type"],
        telegram_file_id=row["telegram_file_id"],
        caption=row.get("caption"),
        recommended_by=BROADCAST_HQ_RECOMMENDED_BY,
        nlikes=int(row.get("nlikes") or 0),
    )
