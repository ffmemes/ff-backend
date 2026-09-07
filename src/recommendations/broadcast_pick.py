"""High-confidence meme selection for retention broadcasts.

Feed queue pop is optimized for continuous scrolling. Reengagement pushes need
a single strong meme that earns a *fast* reaction when the user returns.
Prefer last-week channel-viral posts (community-verified forwards), then liked
sources + proven like rate. Never majority-dislike sources.
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
from src.tgbot.constants import TELEGRAM_CHANNEL_EN_CHAT_ID, TELEGRAM_CHANNEL_RU_CHAT_ID

logger = logging.getLogger(__name__)

# Delivery-path labels for analytics (dwell / reactivation).
BROADCAST_RECOMMENDED_BY = "broadcast_reengagement"
BROADCAST_HQ_RECOMMENDED_BY = "broadcast_reengagement_hq"
BROADCAST_CHANNEL_VIRAL_RECOMMENDED_BY = "broadcast_channel_viral"
_CHANNEL_HITS_EXPERIMENT_ID = "channel_hits_v1"

# Quality floors for the HQ pick (explicit reactions, not lr_smoothed alone).
_HQ_MIN_EXPLICIT_REACTIONS = 15
_HQ_MIN_RAW_LIKE_RATE = 0.45


async def pick_reengagement_meme(user_id: int) -> tuple[MemeData | None, str]:
    """Return (meme, recommended_by_label) for a retention push.

    Tries last-7-day channel-viral posts first (label ``broadcast_channel_viral``),
    then the affinity HQ pick (``broadcast_reengagement_hq``), then the feed
    queue (``broadcast_reengagement``). Channel-hit experiment users skip the
    viral path so the feed test stays the only channel-viral treatment.
    """
    if settings.BROADCAST_CHANNEL_VIRAL_PICK_ENABLED:
        meme = await _fetch_channel_viral_reengagement_meme(user_id)
        if meme is not None:
            return meme, BROADCAST_CHANNEL_VIRAL_RECOMMENDED_BY

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
    return _meme_from_row(row, BROADCAST_HQ_RECOMMENDED_BY)


async def _fetch_channel_viral_reengagement_meme(user_id: int) -> MemeData | None:
    """Unseen image from our channels in the last 7 days, ranked by forwards.

    Skips known subscribers (they already got the channel push) and anyone in
    the live channel-hits cohort. Empty pool is normal — HQ/queue still fire.
    """
    query = """
        SELECT
            M.id
            , M.type
            , M.telegram_file_id
            , M.caption
            , COALESCE(MS.nlikes, 0) AS nlikes
        FROM crossposting CP
        INNER JOIN meme M
            ON M.id = CP.meme_id
        LEFT JOIN meme_stats MS
            ON MS.meme_id = M.id
        INNER JOIN user_language L
            ON L.language_code = M.language_code
            AND L.user_id = :user_id
        INNER JOIN LATERAL (
            SELECT S.views, S.forwards
            FROM crossposting_snapshots S
            WHERE S.channel = CP.channel
              AND S.meme_id = CP.meme_id
              AND S.telegram_message_id = CP.telegram_message_id
            ORDER BY S.snapshot_at DESC
            LIMIT 1
        ) SNAP ON TRUE
        LEFT JOIN user_meme_reaction R
            ON R.meme_id = M.id
            AND R.user_id = :user_id
        WHERE CP.channel IN ('tgchannelru', 'tgchannelen')
          AND CP.created_at >= (NOW() AT TIME ZONE 'UTC') - interval '7 days'
          AND CP.created_at < (NOW() AT TIME ZONE 'UTC') - interval '24 hours'
          AND M.status = 'published'
          AND M.type = 'image'
          AND M.duplicate_of IS NULL
          AND M.telegram_file_id IS NOT NULL
          AND R.meme_id IS NULL
          AND SNAP.views >= 50
          AND SNAP.forwards >= 1
          AND NOT EXISTS (
              SELECT 1 FROM experiment_assignment A
              WHERE A.user_id = :user_id
                AND A.experiment_id = :experiment_id
                AND CAST(A.assignment_metadata->>'exposure_end_at' AS timestamptz) > NOW()
          )
          AND NOT EXISTS (
              SELECT 1 FROM user_channel_membership CM
              WHERE CM.user_id = :user_id
                AND CM.chat_id = CASE CP.channel
                    WHEN 'tgchannelru' THEN CAST(:ru_chat_id AS bigint)
                    ELSE CAST(:en_chat_id AS bigint) END
                AND (CM.status = 'member' OR CM.ever_member)
          )
          AND NOT EXISTS (
              SELECT 1 FROM user_tg_chat_membership OLD
              WHERE OLD.user_tg_id = :user_id
                AND OLD.chat_id = CASE CP.channel
                    WHEN 'tgchannelru' THEN CAST(:ru_chat_id AS bigint)
                    ELSE CAST(:en_chat_id AS bigint) END
          )
        ORDER BY SNAP.forwards DESC, SNAP.views DESC, CP.created_at DESC
        LIMIT 1
    """
    row = await fetch_one(
        text(query),
        {
            "user_id": user_id,
            "experiment_id": _CHANNEL_HITS_EXPERIMENT_ID,
            "ru_chat_id": TELEGRAM_CHANNEL_RU_CHAT_ID,
            "en_chat_id": TELEGRAM_CHANNEL_EN_CHAT_ID,
        },
    )
    return _meme_from_row(row, BROADCAST_CHANNEL_VIRAL_RECOMMENDED_BY)


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
