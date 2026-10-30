import math
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from src.config import settings
from src.crossposting.constants import Channel
from src.crossposting.shadow_score import SHADOW_V5_VERSION, attach_v5_ranks, score_v5
from src.database import (
    crossposting,
    crossposting_decision_log,
    execute,
    fetch_all,
    fetch_one,
)
from src.tgbot.constants import TELEGRAM_CHANNEL_EN_CHAT_ID, TELEGRAM_CHANNEL_RU_CHAT_ID

# score_version in crossposting + decision_log
SCORE_VERSION_V2 = 2
# RU: v2 factors × ln(nlikes+1) — meme-level like volume (docs/analyst/readouts/2026-08-09-…)
SCORE_VERSION_MEME_LIKE_VOLUME = 4


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


# Scheduled slots are >= 2h apart; a newer post means late runs are catching up.
CATCH_UP_GAP_MINUTES = 60


async def posted_recently(channel: Channel, minutes: int = CATCH_UP_GAP_MINUTES) -> bool:
    """True if this channel got a post within ``minutes`` (stops catch-up bursts)."""
    row = await fetch_one(
        text(
            """
            SELECT 1 FROM crossposting
            WHERE channel = :channel
              AND created_at > NOW() - make_interval(mins => :minutes)
              -- weekly reward albums (REWARD_ALBUM_SCORE_VERSION = 0) are not ranked slots
              AND score_version IS DISTINCT FROM 0
            LIMIT 1
            """
        ),
        {"channel": channel.value, "minutes": minutes},
    )
    return row is not None


# Per-channel ranker constants (mirror the SQL ORDER BY).
_CHANNEL_PARAMS: dict[str, dict[str, Any]] = {
    "tgchannelru": {"impr_penalty": 0.8, "age_threshold": 7, "language_code": "ru"},
    "tgchannelen": {"impr_penalty": 0.5, "age_threshold": 90, "language_code": "en"},
}


def _compute_score_breakdown(
    row: dict[str, Any],
    channel: str,
    *,
    like_volume_enabled: bool = False,
) -> dict[str, Any]:
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
    # Meme-level volume (not LR): prefers "well tested in bot" over high-LR sparse.
    like_volume_factor = math.log(float(nlikes) + 1.0) if like_volume_enabled else 1.0

    final_score = (
        lr_factor
        * impr_factor
        * age_factor
        * caption_factor
        * sent_factor
        * src_quality_mult
        * invited_boost
        * like_volume_factor
    )

    out = {
        "lr_factor": round(lr_factor, 4),
        "impr_factor": round(impr_factor, 4),
        "age_factor": round(age_factor, 4),
        "caption_factor": round(caption_factor, 4),
        "sent_factor": round(sent_factor, 4),
        "src_quality_mult": round(src_quality_mult, 4),
        "invited_boost": round(invited_boost, 4),
        "like_volume_factor": round(like_volume_factor, 4),
        "like_volume_enabled": like_volume_enabled,
        "final_score": round(final_score, 6),
    }
    return out


def _build_decision_log(
    channel: str,
    score_version: int,
    candidates: list[dict[str, Any]],
    *,
    like_volume_enabled: bool = False,
) -> dict[str, Any] | None:
    """Build the kwargs dict for log_ranker_decision from a top-N candidate list.
    Returns None if candidates is empty."""
    if not candidates:
        return None
    picked = candidates[0]
    log_candidates = []
    for i, row in enumerate(candidates):
        breakdown = _compute_score_breakdown(row, channel, like_volume_enabled=like_volume_enabled)
        log_candidate = {
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
            "n_sub_likes": int(row.get("n_sub_likes") or 0),
            "caption_present": row.get("caption") is not None,
            "src_signal": (
                round(float(row["src_signal"]), 4) if row.get("src_signal") is not None else None
            ),
            **breakdown,
            # v5 shadow (log only): see shadow_score.py; None when enrichment failed.
            "shadow_version": SHADOW_V5_VERSION,
            "theta_src": row.get("theta_src"),
            "user_taste_z": row.get("user_taste_z"),
            "score_v5": (
                round(score_v5(channel, row["nlikes"], row["theta_src"], row["user_taste_z"]), 6)
                if row.get("theta_src") is not None
                else None
            ),
        }
        log_candidates.append(log_candidate)

    # Shadow ranks among this top-N only (production order unchanged).
    # Keep shadow_* only inside candidates[] — log_ranker_decision kwargs are fixed columns.
    log_candidates = attach_v5_ranks(log_candidates)

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


# v5 shadow inputs per candidate, one bounded query per decision (~1.3s on prod).
# Labels: zf = ln(1+forwards) - channel×MSK-week mean over image posts 48h..365d old.
# ``crossposting.forwards`` is the latest Telethon snapshot (frozen once the post
# leaves the 30d sweep) — the same field the 2026-10-30 study used, not a 24h snapshot.
# theta_src: Beta(hits + 4·p̄, misses + 4·(1−p̄)) posterior mean / p̄, clip 0.5–2,
#   hit = top quartile of ln(1+forwards) within its week.
# user_taste_z: user weight w = Σ zf of liked posts (liked before the post) / (n + 20);
#   meme taste = Σ w of its likers / n_likes / stddev(w).
# ponytail: likes limited to sent_at > now()-90d — user_meme_reaction has no valid
#   meme_id-leading index on prod, so this window keeps the scan bounded. Widen it
#   (or precompute weights) if user coverage proves too thin.
_V5_SHADOW_QUERY = """
    WITH posts AS MATERIALIZED (
        SELECT cp.meme_id, cp.created_at, m.meme_source_id AS src,
               LN(1 + cp.forwards) AS lfw,
               date_trunc('week', cp.created_at + INTERVAL '3 hours') AS wk
        FROM crossposting cp
        JOIN meme m ON m.id = cp.meme_id
        WHERE cp.channel = :channel
          AND cp.telegram_message_id IS NOT NULL
          AND cp.views > 0
          AND cp.forwards IS NOT NULL
          AND m.type = 'image'
          AND cp.created_at < NOW() - INTERVAL '48 hours'
          AND cp.created_at > NOW() - INTERVAL '365 days'
    ),
    weeks AS (
        SELECT wk, AVG(lfw) AS mu,
               PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY lfw) AS q75
        FROM posts GROUP BY wk
    ),
    labeled AS MATERIALIZED (
        SELECT p.meme_id, p.created_at, p.src,
               p.lfw - w.mu AS zf, (p.lfw >= w.q75)::int AS hit
        FROM posts p JOIN weeks w USING (wk)
    ),
    pbar AS (SELECT AVG(hit) AS p FROM labeled),
    src AS (SELECT src, SUM(hit) AS h, COUNT(*) AS n FROM labeled GROUP BY src),
    likes AS MATERIALIZED (
        SELECT r.meme_id, r.user_id, r.reacted_at
        FROM user_meme_reaction r
        WHERE r.sent_at > NOW() - INTERVAL '90 days'
          AND r.reaction_id = 1
    ),
    users AS MATERIALIZED (
        SELECT lk.user_id, SUM(l.zf) / (COUNT(*) + 20) AS w
        FROM labeled l
        JOIN likes lk ON lk.meme_id = l.meme_id AND lk.reacted_at < l.created_at
        GROUP BY lk.user_id
    ),
    wsd AS (SELECT NULLIF(STDDEV_POP(w), 0) AS sd FROM users),
    taste AS (
        SELECT lk.meme_id, COUNT(*) AS n_likes, SUM(COALESCE(u.w, 0)) AS wsum
        FROM likes lk LEFT JOIN users u USING (user_id)
        WHERE lk.meme_id = ANY(:meme_ids)
        GROUP BY lk.meme_id
    )
    SELECT m.id AS meme_id,
           LEAST(2.0, GREATEST(0.5,
               (COALESCE(s.h, 0) + 4 * pbar.p) / (COALESCE(s.n, 0) + 4) / pbar.p
           ))::float AS theta_src,
           COALESCE(t.wsum / GREATEST(t.n_likes, 1) / wsd.sd, 0)::float AS user_taste_z
    FROM meme m
    CROSS JOIN pbar CROSS JOIN wsd
    LEFT JOIN src s ON s.src = m.meme_source_id
    LEFT JOIN taste t ON t.meme_id = m.id
    WHERE m.id = ANY(:meme_ids)
"""


async def _enrich_candidates_with_v5_shadow(
    candidates: list[dict[str, Any]],
    *,
    channel: str,
) -> list[dict[str, Any]]:
    """Attach theta_src + user_taste_z for top-N (does not re-rank)."""
    meme_ids = [int(c["id"]) for c in candidates]
    if not meme_ids:
        return candidates
    rows = await fetch_all(text(_V5_SHADOW_QUERY), {"channel": channel, "meme_ids": meme_ids})
    by_id = {int(r["meme_id"]): r for r in rows}
    for c in candidates:
        r = by_id.get(int(c["id"]))
        if r is not None:
            c["theta_src"] = round(float(r["theta_src"]), 4)
            c["user_taste_z"] = round(float(r["user_taste_z"]), 4)
    return candidates


async def _enrich_candidates_with_sub_likes(
    candidates: list[dict[str, Any]],
    *,
    channel: str,
) -> list[dict[str, Any]]:
    """Attach n_sub_likes: pre-existing likes from known channel members (shadow).

    Membership comes from ``user_tg_chat_membership`` (bot-observed). Does not re-rank.
    """
    if not candidates:
        return candidates
    chat_id = (
        TELEGRAM_CHANNEL_RU_CHAT_ID
        if channel == "tgchannelru"
        else TELEGRAM_CHANNEL_EN_CHAT_ID
        if channel == "tgchannelen"
        else None
    )
    if chat_id is None:
        for c in candidates:
            c["n_sub_likes"] = 0
        return candidates

    meme_ids = [int(c["id"]) for c in candidates if c.get("id") is not None]
    counts: dict[int, int] = {}
    if meme_ids:
        rows = await fetch_all(
            text(
                """
                SELECT umr.meme_id, COUNT(DISTINCT umr.user_id)::int AS n_sub
                FROM user_meme_reaction umr
                WHERE umr.reaction_id = 1
                  AND umr.meme_id = ANY(:meme_ids)
                  AND EXISTS (
                    SELECT 1
                    FROM user_tg_chat_membership m
                    WHERE m.user_tg_id = umr.user_id
                      AND m.chat_id = :chat_id
                  )
                GROUP BY umr.meme_id
                """
            ),
            {"meme_ids": meme_ids, "chat_id": int(chat_id)},
        )
        counts = {int(r["meme_id"]): int(r["n_sub"]) for r in rows}

    for c in candidates:
        mid = int(c["id"]) if c.get("id") is not None else None
        c["n_sub_likes"] = counts.get(mid, 0) if mid is not None else 0
    return candidates


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


_STANDARD_RANKER_QUERY = """
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
        WHERE cp.channel = :channel
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
        WHERE cp2.channel = :channel
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
                    * CASE WHEN MS.raw_impr_rank <= 1 THEN 1 ELSE :impr_penalty END
                    * CASE WHEN MS.age_days < :age_threshold THEN 1 ELSE 0.8 END
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
                    * (1.0 + LEAST(MS.invited_count, 10) * 0.1)
                    -- meme-level volume (score_version=4): ln(nlikes+1); weight 0 → 1.0
                    * CASE
                        WHEN :like_volume_enabled THEN LN(COALESCE(MS.nlikes, 0) + 1.0)
                        ELSE 1.0
                      END,
                    M.id
            ) AS candidate_rank
        FROM meme M
        INNER JOIN meme_stats MS ON MS.meme_id = M.id
        LEFT JOIN crossposting CP ON CP.meme_id = M.id AND CP.channel = :channel
        LEFT JOIN src_quality SQ ON SQ.meme_source_id = M.meme_source_id
        WHERE 1=1
          AND CP.meme_id IS NULL
          AND M.status = 'ok'
          AND M.language_code = :language_code
          AND M.type = 'image'
          AND MS.nlikes >= 5
          AND M.meme_source_id NOT IN (SELECT meme_source_id FROM recent_src)
        ORDER BY -1
            * COALESCE((MS.nlikes + 1.) / (MS.nlikes + MS.ndislikes + 1), 0.5)
            * CASE WHEN MS.raw_impr_rank <= 1 THEN 1 ELSE :impr_penalty END
            * CASE WHEN MS.age_days < :age_threshold THEN 1 ELSE 0.8 END
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
            * (1.0 + LEAST(MS.invited_count, 10) * 0.1)
            * CASE
                WHEN :like_volume_enabled THEN LN(COALESCE(MS.nlikes, 0) + 1.0)
                ELSE 1.0
              END,
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
                udll.deep_link FROM ('^[ms]_([1-9][0-9]{0,18})_' || ranked.id || '$')
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


async def _get_next_meme_for_channel(
    channel: str,
    *,
    log_top_n: int,
    score_version: int,
    like_volume_enabled: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    params = {
        **_CHANNEL_PARAMS[channel],
        "channel": channel,
        "limit": log_top_n,
        "like_volume_enabled": like_volume_enabled,
    }
    rows = await fetch_all(text(_STANDARD_RANKER_QUERY), params)
    if not rows:
        return None, None
    # Shadow enrichments must never block posting (log-only signals).
    try:
        rows = await _enrich_candidates_with_v5_shadow(rows, channel=channel)
    except Exception:
        import logging

        logging.getLogger(__name__).warning("v5 shadow enrichment failed", exc_info=True)
    try:
        rows = await _enrich_candidates_with_sub_likes(rows, channel=channel)
    except Exception:
        import logging

        logging.getLogger(__name__).warning("sub-likes shadow enrichment failed", exc_info=True)
    return (
        _picked_meme_dict(rows[0]),
        _build_decision_log(
            channel,
            score_version,
            rows,
            like_volume_enabled=like_volume_enabled,
        ),
    )


def _ru_like_volume_ranker_enabled() -> bool:
    return bool(settings.CROSSPOST_RU_MEME_LIKE_VOLUME_ENABLED)


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

    When ``CROSSPOST_RU_MEME_LIKE_VOLUME_ENABLED`` (default ON), uses
    ``score_version=4``: v2 factors × ``ln(nlikes+1)`` so high bot-exposure
    memes win within source prior (offline H6). Kill switch → v2.
    """
    like_vol = _ru_like_volume_ranker_enabled()
    return await _get_next_meme_for_channel(
        "tgchannelru",
        log_top_n=log_top_n,
        score_version=(SCORE_VERSION_MEME_LIKE_VOLUME if like_vol else SCORE_VERSION_V2),
        like_volume_enabled=like_vol,
    )


async def get_next_meme_for_tgchannelen(
    log_top_n: int = 5,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Same as :func:`get_next_meme_for_tgchannelru` but for @fast_food_memes (EN).

    EN stays on score_version=2 (no like-volume factor) until offline gate passes.
    """
    return await _get_next_meme_for_channel(
        "tgchannelen",
        log_top_n=log_top_n,
        score_version=SCORE_VERSION_V2,
        like_volume_enabled=False,
    )
