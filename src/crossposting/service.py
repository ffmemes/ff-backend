from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from src.crossposting.constants import Channel
from src.database import (
    crossposting,
    crossposting_decision_log,
    execute,
    fetch_all,
)


async def log_meme_sent(
    meme_id: int,
    channel: Channel,
    telegram_message_id: int | None = None,
    caption_text: str | None = None,
    score_version: int = 1,
) -> None:
    # ON CONFLICT DO NOTHING: rewrite-on-repost would corrupt source-quality
    # measurements (drop the original mature sample out of the [30d, 48h]
    # window and overwrite its views/forwards with the reward post's stats).
    # Reward reposts of already-crossposted memes therefore don't refresh
    # the diversity cap — acceptable since rewards run weekly.
    insert_statement = (
        insert(crossposting)
        .values(
            meme_id=meme_id,
            channel=channel.value,
            telegram_message_id=telegram_message_id,
            caption_text=caption_text,
            score_version=score_version,
        )
        .on_conflict_do_nothing()
    )

    await execute(insert_statement)


# Per-channel ranker constants (mirror the SQL ORDER BY).
_CHANNEL_PARAMS: dict[str, dict[str, Any]] = {
    "tgchannelru": {"impr_penalty": 0.8, "age_threshold": 7},
    "tgchannelen": {"impr_penalty": 0.5, "age_threshold": 90},
}


def _compute_score_breakdown(row: dict[str, Any], channel: str) -> dict[str, Any]:
    """Reproduce the SQL ORDER BY in Python so each candidate gets a logged score
    breakdown. Must stay in sync with the ORDER BY in the SQL queries below."""
    params = _CHANNEL_PARAMS[channel]
    nlikes = row.get("nlikes") or 0
    ndislikes = row.get("ndislikes") or 0
    nmemes_sent = row.get("nmemes_sent") or 0
    raw_impr_rank = row.get("raw_impr_rank")
    age_days = row.get("age_days") or 0
    invited_count = row.get("invited_count") or 0
    src_signal = row.get("src_signal")
    median_signal = row.get("median_signal")
    caption_present = row.get("caption") is not None

    denom = nlikes + ndislikes + 1
    lr_factor = (nlikes + 1.0) / denom if denom else 0.5
    impr_factor = (
        1.0 if (raw_impr_rank is not None and raw_impr_rank <= 1) else params["impr_penalty"]
    )
    age_factor = 1.0 if age_days < params["age_threshold"] else 0.8
    caption_factor = 0.8 if caption_present else 1.0
    sent_factor = 1.0 if nmemes_sent <= 1 else (nlikes + ndislikes) / nmemes_sent

    if src_signal is not None and median_signal:
        # SQL returns NUMERIC as Decimal; cast both sides for safe arithmetic.
        src_quality_mult = max(0.5, min(2.0, float(src_signal) / float(median_signal)))
    else:
        src_quality_mult = 1.0

    invited_boost = 1.0 + min(invited_count, 10) * 0.1

    final_score = (
        lr_factor
        * impr_factor
        * age_factor
        * caption_factor
        * sent_factor
        * src_quality_mult
        * invited_boost
    )

    return {
        "lr_factor": round(lr_factor, 4),
        "impr_factor": round(impr_factor, 4),
        "age_factor": round(age_factor, 4),
        "caption_factor": round(caption_factor, 4),
        "sent_factor": round(sent_factor, 4),
        "src_quality_mult": round(src_quality_mult, 4),
        "invited_boost": round(invited_boost, 4),
        "final_score": round(final_score, 6),
    }


def _build_decision_log(
    channel: str,
    score_version: int,
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Build the kwargs dict for log_ranker_decision from a top-N candidate list.
    Returns None if candidates is empty."""
    if not candidates:
        return None
    picked = candidates[0]
    log_candidates = []
    for i, row in enumerate(candidates):
        breakdown = _compute_score_breakdown(row, channel)
        log_candidates.append(
            {
                "rank": i + 1,
                "meme_id": row["id"],
                "source_id": row.get("meme_source_id"),
                "nlikes": row.get("nlikes"),
                "ndislikes": row.get("ndislikes"),
                "raw_impr_rank": row.get("raw_impr_rank"),
                "age_days": row.get("age_days"),
                "nmemes_sent": row.get("nmemes_sent"),
                "invited_count": row.get("invited_count"),
                "pre_inbot_share_clicks": row.get("pre_inbot_share_clicks") or 0,
                "pre_inbot_share_click_users": row.get("pre_inbot_share_click_users") or 0,
                "caption_present": row.get("caption") is not None,
                "src_signal": (
                    round(float(row["src_signal"]), 4)
                    if row.get("src_signal") is not None
                    else None
                ),
                **breakdown,
            }
        )
    return {
        "channel": channel,
        "picked_meme_id": picked["id"],
        "score_version": score_version,
        "median_signal": (
            round(float(picked["median_signal"]), 4)
            if picked.get("median_signal") is not None
            else None
        ),
        "pool_size": picked.get("candidate_pool_size"),
        "candidates": log_candidates,
    }


async def log_ranker_decision(
    channel: str,
    picked_meme_id: int | None,
    score_version: int,
    median_signal: float | None,
    pool_size: int | None,
    candidates: list[dict[str, Any]],
) -> None:
    """Insert one row into crossposting_decision_log. Failures must be wrapped
    in try/except by the caller (logging miss << duplicate album publish).
    """
    insert_stmt = insert(crossposting_decision_log).values(
        channel=channel,
        picked_meme_id=picked_meme_id,
        score_version=score_version,
        median_signal=median_signal,
        candidate_pool_size=pool_size,
        candidates=candidates,
    )
    await execute(insert_stmt)


# Columns exposed for MemeData construction. Keep narrow — adding fields here
# would require matching changes in src/storage/schemas.py:MemeData.
_PICKED_FIELDS = ("id", "type", "telegram_file_id", "caption")


def _picked_meme_dict(candidate: dict[str, Any]) -> dict[str, Any]:
    return {k: candidate[k] for k in _PICKED_FIELDS}


_RU_QUERY = """
    WITH selected_at AS (
        SELECT NOW() AS decided_at
    ),
    src_quality AS (
        SELECT
            m.meme_source_id,
            AVG(cp.forwards * SQRT(GREATEST(cp.views, 1) / 100.0)) AS signal,
            COUNT(*) AS n_posts
        FROM crossposting cp
        JOIN meme m ON m.id = cp.meme_id
        WHERE cp.channel = 'tgchannelru'
          AND cp.created_at > NOW() - INTERVAL '30 days'
          AND cp.created_at < NOW() - INTERVAL '48 hours'
          AND cp.views IS NOT NULL
          AND cp.views > 0
          AND m.type = 'image'
        GROUP BY m.meme_source_id
        HAVING COUNT(*) >= 5
    ),
    src_median AS (
        SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY signal) AS m_signal
        FROM src_quality
    ),
    recent_src AS (
        SELECT DISTINCT m2.meme_source_id
        FROM crossposting cp2
        JOIN meme m2 ON m2.id = cp2.meme_id
        WHERE cp2.channel = 'tgchannelru'
          AND cp2.created_at > NOW() - INTERVAL '24 hours'
          AND cp2.telegram_message_id IS NOT NULL
    ),
    ranked AS (
        SELECT
            M.id, M.type, M.telegram_file_id, M.caption,
            M.meme_source_id,
            MS.nlikes, MS.ndislikes, MS.raw_impr_rank,
            MS.age_days, MS.nmemes_sent, MS.invited_count,
            SQ.signal AS src_signal,
            (SELECT m_signal FROM src_median) AS median_signal,
            COUNT(*) OVER () AS candidate_pool_size,
            ROW_NUMBER() OVER (
                ORDER BY -1
                    * COALESCE((MS.nlikes + 1.) / (MS.nlikes + MS.ndislikes + 1), 0.5)
                    * CASE WHEN MS.raw_impr_rank <= 1 THEN 1 ELSE 0.8 END
                    * CASE WHEN MS.age_days < 7 THEN 1 ELSE 0.8 END
                    * CASE WHEN M.caption IS NULL THEN 1 ELSE 0.8 END
                    * CASE
                        WHEN MS.nmemes_sent <= 1 THEN 1
                        ELSE (MS.nlikes + MS.ndislikes) * 1. / MS.nmemes_sent
                      END
                    * COALESCE(
                        LEAST(2.0, GREATEST(0.5,
                            SQ.signal / NULLIF((SELECT m_signal FROM src_median), 0)
                        )),
                        1.0
                      )
                    * (1.0 + LEAST(MS.invited_count, 10) * 0.1),
                    M.id
            ) AS candidate_rank
        FROM meme M
        INNER JOIN meme_stats MS ON MS.meme_id = M.id
        LEFT JOIN crossposting CP ON CP.meme_id = M.id AND CP.channel = 'tgchannelru'
        LEFT JOIN src_quality SQ ON SQ.meme_source_id = M.meme_source_id
        WHERE 1=1
          AND CP.meme_id IS NULL
          AND M.status = 'ok'
          AND M.language_code = 'ru'
          AND M.type = 'image'
          AND MS.nlikes >= 5
          AND M.meme_source_id NOT IN (SELECT meme_source_id FROM recent_src)
        ORDER BY -1
            * COALESCE((MS.nlikes + 1.) / (MS.nlikes + MS.ndislikes + 1), 0.5)
            * CASE WHEN MS.raw_impr_rank <= 1 THEN 1 ELSE 0.8 END
            * CASE WHEN MS.age_days < 7 THEN 1 ELSE 0.8 END
            * CASE WHEN M.caption IS NULL THEN 1 ELSE 0.8 END
            * CASE
                WHEN MS.nmemes_sent <= 1 THEN 1
                ELSE (MS.nlikes + MS.ndislikes) * 1. / MS.nmemes_sent
              END
            * COALESCE(
                LEAST(2.0, GREATEST(0.5,
                    SQ.signal / NULLIF((SELECT m_signal FROM src_median), 0)
                )),
                1.0
              )
            * (1.0 + LEAST(MS.invited_count, 10) * 0.1),
            M.id
        LIMIT :limit
    )
    SELECT
        ranked.*,
        COALESCE(share_clicks.pre_inbot_share_clicks, 0) AS pre_inbot_share_clicks,
        COALESCE(share_clicks.pre_inbot_share_click_users, 0) AS pre_inbot_share_click_users
    FROM ranked
    CROSS JOIN selected_at
    LEFT JOIN LATERAL (
        SELECT
            COUNT(*) AS pre_inbot_share_clicks,
            COUNT(DISTINCT user_id) AS pre_inbot_share_click_users
        FROM user_deep_link_log udll
        CROSS JOIN LATERAL (
            SELECT substring(
                udll.deep_link FROM ('^s_([1-9][0-9]{0,18})_' || ranked.id || '$')
            ) AS sharer_id
        ) share_link
        WHERE udll.created_at < selected_at.decided_at
          AND CASE
              WHEN share_link.sharer_id IS NULL THEN false
              WHEN length(share_link.sharer_id) = 19
                AND share_link.sharer_id > '9223372036854775807' THEN false
              ELSE udll.user_id <> share_link.sharer_id::bigint
          END
    ) share_clicks ON true
    ORDER BY ranked.candidate_rank
"""

_EN_QUERY = """
    WITH selected_at AS (
        SELECT NOW() AS decided_at
    ),
    src_quality AS (
        SELECT
            m.meme_source_id,
            AVG(cp.forwards * SQRT(GREATEST(cp.views, 1) / 100.0)) AS signal,
            COUNT(*) AS n_posts
        FROM crossposting cp
        JOIN meme m ON m.id = cp.meme_id
        WHERE cp.channel = 'tgchannelen'
          AND cp.created_at > NOW() - INTERVAL '30 days'
          AND cp.created_at < NOW() - INTERVAL '48 hours'
          AND cp.views IS NOT NULL
          AND cp.views > 0
          AND m.type = 'image'
        GROUP BY m.meme_source_id
        HAVING COUNT(*) >= 5
    ),
    src_median AS (
        SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY signal) AS m_signal
        FROM src_quality
    ),
    recent_src AS (
        SELECT DISTINCT m2.meme_source_id
        FROM crossposting cp2
        JOIN meme m2 ON m2.id = cp2.meme_id
        WHERE cp2.channel = 'tgchannelen'
          AND cp2.created_at > NOW() - INTERVAL '24 hours'
          AND cp2.telegram_message_id IS NOT NULL
    ),
    ranked AS (
        SELECT
            M.id, M.type, M.telegram_file_id, M.caption,
            M.meme_source_id,
            MS.nlikes, MS.ndislikes, MS.raw_impr_rank,
            MS.age_days, MS.nmemes_sent, MS.invited_count,
            SQ.signal AS src_signal,
            (SELECT m_signal FROM src_median) AS median_signal,
            COUNT(*) OVER () AS candidate_pool_size,
            ROW_NUMBER() OVER (
                ORDER BY -1
                    * COALESCE((MS.nlikes + 1.) / (MS.nlikes + MS.ndislikes + 1), 0.5)
                    * CASE WHEN MS.raw_impr_rank <= 1 THEN 1 ELSE 0.5 END
                    * CASE WHEN MS.age_days < 90 THEN 1 ELSE 0.8 END
                    * CASE WHEN M.caption IS NULL THEN 1 ELSE 0.8 END
                    * CASE
                        WHEN MS.nmemes_sent <= 1 THEN 1
                        ELSE (MS.nlikes + MS.ndislikes) * 1. / MS.nmemes_sent
                      END
                    * COALESCE(
                        LEAST(2.0, GREATEST(0.5,
                            SQ.signal / NULLIF((SELECT m_signal FROM src_median), 0)
                        )),
                        1.0
                      )
                    * (1.0 + LEAST(MS.invited_count, 10) * 0.1),
                    M.id
            ) AS candidate_rank
        FROM meme M
        INNER JOIN meme_stats MS ON MS.meme_id = M.id
        LEFT JOIN crossposting CP ON CP.meme_id = M.id AND CP.channel = 'tgchannelen'
        LEFT JOIN src_quality SQ ON SQ.meme_source_id = M.meme_source_id
        WHERE 1=1
          AND CP.meme_id IS NULL
          AND M.status = 'ok'
          AND M.language_code = 'en'
          AND M.type = 'image'
          AND MS.nlikes >= 5
          AND M.meme_source_id NOT IN (SELECT meme_source_id FROM recent_src)
        ORDER BY -1
            * COALESCE((MS.nlikes + 1.) / (MS.nlikes + MS.ndislikes + 1), 0.5)
            * CASE WHEN MS.raw_impr_rank <= 1 THEN 1 ELSE 0.5 END
            * CASE WHEN MS.age_days < 90 THEN 1 ELSE 0.8 END
            * CASE WHEN M.caption IS NULL THEN 1 ELSE 0.8 END
            * CASE
                WHEN MS.nmemes_sent <= 1 THEN 1
                ELSE (MS.nlikes + MS.ndislikes) * 1. / MS.nmemes_sent
              END
            * COALESCE(
                LEAST(2.0, GREATEST(0.5,
                    SQ.signal / NULLIF((SELECT m_signal FROM src_median), 0)
                )),
                1.0
              )
            * (1.0 + LEAST(MS.invited_count, 10) * 0.1),
            M.id
        LIMIT :limit
    )
    SELECT
        ranked.*,
        COALESCE(share_clicks.pre_inbot_share_clicks, 0) AS pre_inbot_share_clicks,
        COALESCE(share_clicks.pre_inbot_share_click_users, 0) AS pre_inbot_share_click_users
    FROM ranked
    CROSS JOIN selected_at
    LEFT JOIN LATERAL (
        SELECT
            COUNT(*) AS pre_inbot_share_clicks,
            COUNT(DISTINCT user_id) AS pre_inbot_share_click_users
        FROM user_deep_link_log udll
        CROSS JOIN LATERAL (
            SELECT substring(
                udll.deep_link FROM ('^s_([1-9][0-9]{0,18})_' || ranked.id || '$')
            ) AS sharer_id
        ) share_link
        WHERE udll.created_at < selected_at.decided_at
          AND CASE
              WHEN share_link.sharer_id IS NULL THEN false
              WHEN length(share_link.sharer_id) = 19
                AND share_link.sharer_id > '9223372036854775807' THEN false
              ELSE udll.user_id <> share_link.sharer_id::bigint
          END
    ) share_clicks ON true
    ORDER BY ranked.candidate_rank
"""


async def get_next_meme_for_tgchannelru(
    log_top_n: int = 5,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Pick the top crosspost candidate for @fastfoodmemes (RU).

    Returns ``(picked_meme, decision_log)``:

    - ``picked_meme`` — narrow dict suitable for ``MemeData(**...)`` construction
      (id, type, telegram_file_id, caption). ``None`` when no candidate passes
      filters.
    - ``decision_log`` — kwargs dict for ``log_ranker_decision``, with the top-N
      candidates and per-candidate score breakdown. ``None`` when no candidates.
    """
    rows = await fetch_all(text(_RU_QUERY), {"limit": log_top_n})
    if not rows:
        return None, None
    return _picked_meme_dict(rows[0]), _build_decision_log("tgchannelru", 2, rows)


async def get_next_meme_for_tgchannelen(
    log_top_n: int = 5,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Same as :func:`get_next_meme_for_tgchannelru` but for @fast_food_memes (EN)."""
    rows = await fetch_all(text(_EN_QUERY), {"limit": log_top_n})
    if not rows:
        return None, None
    return _picked_meme_dict(rows[0]), _build_decision_log("tgchannelen", 2, rows)


async def get_next_meme_for_vkgroupru():
    pass
