import asyncio
import logging
from typing import Any

from sqlalchemy import text

from src.database import fetch_all, fetch_one
from src.recommendations.utils import (
    block_disliked_sources_sql_filter,
    disliked_source_demote_sql,
    exclude_meme_ids_sql_filter,
)

logger = logging.getLogger(__name__)

# Quality thresholds for the goat pool.
# Memes must have enough data and age to be considered "greatest of all time".
GOAT_MIN_REACTIONS = 10  # (nlikes + ndislikes) — enough statistical signal
GOAT_MIN_LR = 0.20  # lr_smoothed — minimum proven like rate
GOAT_MIN_AGE_DAYS = 3  # days since created_at — must have aged enough to accumulate reactions
GOAT_RECENTLY_SENT_WINDOW_DAYS = 30
TEXT_LIGHT_MAX_OCR_WORDS = 30
# Cold-start first-impression floors (raw LR, not bias-corrected lr_smoothed).
# 7d prod: cold_start_explore_guarded LR ~18% — raise the bar so phase-1 only
# serves memes the crowd already likes at a majority rate.
COLD_START_EXPLORE_MIN_EXPLICIT_REACTIONS = 25
COLD_START_EXPLORE_MIN_LR_SMOOTHED = 0.10
COLD_START_EXPLORE_MIN_RAW_LIKE_RATE = 0.50
COLD_START_GUARDRAIL_SOURCE_URLS = (
    "https://vk.com/dfzwe4",
    "https://vk.com/eternalclassic",
    "https://t.me/ukrmemesmineproblemes",
    "https://t.me/hindi_jokes_desi_memes",
)
COLD_START_EXPLORE_RECOMMENDED_BY = "cold_start_explore"
COLD_START_ADAPT_RECOMMENDED_BY = "cold_start_adapt"
COLD_START_EXPLORE_GUARDED_RECOMMENDED_BY = "cold_start_explore_guarded"
COLD_START_ADAPT_GUARDED_RECOMMENDED_BY = "cold_start_adapt_guarded"

_OCR_TEXT_SQL = "trim(coalesce(M.ocr_result->>'text', M.ocr_result->'raw_result'->>'ocr_text', ''))"
TEXT_LIGHT_OCR_FILTER_SQL = f"""
            AND (
                CASE
                    WHEN {_OCR_TEXT_SQL} = '' THEN 0
                    ELSE cardinality(regexp_split_to_array({_OCR_TEXT_SQL}, '[[:space:]]+'))
                END
            ) <= :text_light_max_ocr_words
"""
COLD_START_GUARDRAIL_SOURCE_FILTER_SQL = """
            AND NOT (S.url = ANY(:cold_start_guardrail_source_urls))
"""


def _build_params(
    user_id: int,
    limit: int,
    exclude_meme_ids: list[int],
    **extra,
) -> dict[str, Any]:
    """Build the standard params dict for candidate queries."""
    params: dict[str, Any] = {"user_id": user_id, "limit": limit, **extra}
    if exclude_meme_ids:
        params["exclude_meme_ids"] = exclude_meme_ids
    return params


def _cold_start_recommended_by(engine: str, candidate_guardrails_enabled: bool) -> str:
    if engine == COLD_START_EXPLORE_RECOMMENDED_BY and candidate_guardrails_enabled:
        return COLD_START_EXPLORE_GUARDED_RECOMMENDED_BY
    if engine == COLD_START_ADAPT_RECOMMENDED_BY and candidate_guardrails_enabled:
        return COLD_START_ADAPT_GUARDED_RECOMMENDED_BY
    return engine


def _cold_start_guardrail_source_filter(candidate_guardrails_enabled: bool) -> str:
    return COLD_START_GUARDRAIL_SOURCE_FILTER_SQL if candidate_guardrails_enabled else ""


def _cold_start_params(
    user_id: int,
    limit: int,
    exclude_meme_ids: list[int],
    *,
    engine: str,
    candidate_guardrails_enabled: bool,
) -> dict[str, Any]:
    params = _build_params(
        user_id,
        limit,
        exclude_meme_ids,
        recommended_by=_cold_start_recommended_by(engine, candidate_guardrails_enabled),
        text_light_max_ocr_words=TEXT_LIGHT_MAX_OCR_WORDS,
    )
    if candidate_guardrails_enabled:
        params["cold_start_guardrail_source_urls"] = list(COLD_START_GUARDRAIL_SOURCE_URLS)
    return params


async def best_uploaded_memes(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
):
    query = f"""
        SELECT
            M.id
            , M.type, M.telegram_file_id, M.caption
            , 'best_uploaded_memes' AS recommended_by
            , COALESCE(MS.nlikes, 0) AS nlikes

        FROM meme M
        INNER JOIN meme_stats MS
            ON MS.meme_id = M.id

        INNER JOIN meme_source S
            ON S.id = M.meme_source_id

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
            AND R.meme_id IS NULL
            AND S.type = 'user upload'
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}
            {block_disliked_sources_sql_filter()}

        ORDER BY -1
            * COALESCE((UMSS.nlikes + 1.) / (UMSS.nlikes + UMSS.ndislikes + 1.), 0.5)
            * {disliked_source_demote_sql()}
            * (MS.nlikes + 1.) / (MS.nlikes + MS.ndislikes + 1.)
        NULLS LAST
        LIMIT :limit
    """
    return await fetch_all(text(query), _build_params(user_id, limit, exclude_meme_ids))


async def like_spread_and_recent_memes(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
):
    query = f"""
        SELECT
            M.id
            , M.type, M.telegram_file_id, M.caption
            , 'like_spread_and_recent' AS recommended_by
            , COALESCE(MS.nlikes, 0) AS nlikes

        FROM meme M
        INNER JOIN meme_stats MS
            ON MS.meme_id = M.id

        INNER JOIN user_language L
            ON L.user_id = :user_id
            AND L.language_code = M.language_code

        LEFT JOIN user_meme_reaction R
                ON R.meme_id = M.id
                AND R.user_id = :user_id

        LEFT JOIN user_meme_source_stats UMSS
            ON UMSS.meme_source_id = M.meme_source_id
            AND UMSS.user_id = :user_id

        WHERE 1=1
            AND M.status = 'ok'
            AND R.meme_id IS NULL

            AND MS.nlikes > MS.ndislikes
            AND MS.raw_impr_rank = 0
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}
            {block_disliked_sources_sql_filter()}
        ORDER BY -1
            * (MS.nlikes - MS.ndislikes) / (MS.nmemes_sent + 1.)
            * {disliked_source_demote_sql()}
        LIMIT :limit
    """
    return await fetch_all(text(query), _build_params(user_id, limit, exclude_meme_ids))


async def _get_lr_smoothed_candidates(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
    min_sends: int = 0,
    recommended_by: str = "lr_smoothed",
    text_light: bool = False,
):
    """
    Uses the following score to rank memes

    score = Like Rate Smoothed * User-Source Like Rate

    Args:
        min_sends: minimum nmemes_sent to filter for statistical confidence.
            Use min_sends=10 for cold start to ensure battle-tested memes.
    """

    min_sends_filter = "AND MS.nmemes_sent >= :min_sends" if min_sends > 0 else ""
    text_light_filter = TEXT_LIGHT_OCR_FILTER_SQL if text_light else ""

    query = f"""
        SELECT
            M.id
            , M.type, M.telegram_file_id, M.caption
            , :recommended_by AS recommended_by
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
            AND R.meme_id IS NULL
            AND MS.nlikes > 1
            {min_sends_filter}
            {text_light_filter}
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}
            {block_disliked_sources_sql_filter()}

        ORDER BY -1
            * COALESCE((UMSS.nlikes + 1.) / (UMSS.nlikes + UMSS.ndislikes + 1.), 0.5)
            * {disliked_source_demote_sql()}
            * MS.lr_smoothed
        LIMIT :limit
    """
    params = _build_params(user_id, limit, exclude_meme_ids, recommended_by=recommended_by)
    if min_sends > 0:
        params["min_sends"] = int(min_sends)
    if text_light:
        params["text_light_max_ocr_words"] = TEXT_LIGHT_MAX_OCR_WORDS
    return await fetch_all(text(query), params)


async def get_lr_smoothed(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
    min_sends: int = 0,
):
    return await _get_lr_smoothed_candidates(
        user_id,
        limit,
        exclude_meme_ids,
        min_sends=min_sends,
        recommended_by="lr_smoothed",
        text_light=False,
    )


async def get_text_light_lr_smoothed(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
    min_sends: int = 0,
):
    return await _get_lr_smoothed_candidates(
        user_id,
        limit,
        exclude_meme_ids,
        min_sends=min_sends,
        recommended_by="text_light_lr_smoothed",
        text_light=True,
    )


async def get_es_ranked(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
):
    """Ranks memes by engagement_score * user-source affinity.

    Same structure as lr_smoothed but uses engagement_score which
    accounts for reaction timing (fast skip = -0.5, slow dislike = -1.0)
    and skip detection (-0.3).
    """

    query = f"""
        SELECT
            M.id
            , M.type, M.telegram_file_id, M.caption
            , 'es_ranked' AS recommended_by
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
            AND R.meme_id IS NULL
            AND MS.engagement_score > 0
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}
            {block_disliked_sources_sql_filter()}

        ORDER BY -1
            * COALESCE((UMSS.nlikes + 1.) / (UMSS.nlikes + UMSS.ndislikes + 1.), 0.5)
            * {disliked_source_demote_sql()}
            * MS.engagement_score
        LIMIT :limit
    """
    return await fetch_all(text(query), _build_params(user_id, limit, exclude_meme_ids))


async def goat(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
):
    # Log global pool size for QA monitoring (no user-specific join needed)
    pool_row = await fetch_one(
        text(
            f"""
            SELECT COUNT(*) AS pool_size
            FROM meme M
            INNER JOIN meme_stats MS ON MS.meme_id = M.id
            WHERE M.status = 'ok'
                AND (MS.nlikes + MS.ndislikes) >= {GOAT_MIN_REACTIONS}
                AND MS.lr_smoothed >= {GOAT_MIN_LR}
                AND M.created_at <= NOW() - INTERVAL '{GOAT_MIN_AGE_DAYS} days'
        """
        ),
        {},
    )
    pool_size = pool_row["pool_size"] if pool_row else 0
    logger.info("goat pool_size=%d", pool_size)

    query = f"""
        WITH SCORES AS MATERIALIZED (
            SELECT
                MS.meme_id,
                MS.nlikes,
                (
                    1.0
                    * (MS.nlikes - MS.ndislikes)::float / (MS.nmemes_sent + 1)
                    * MS.lr_smoothed
                    * (MS.nlikes + MS.ndislikes)::float / (MS.nmemes_sent + 1)
                    * CASE WHEN MS.sec_to_react BETWEEN 2 AND 10 THEN 1 ELSE 0.6 END
                    * CASE WHEN MS.invited_count > 0 THEN 1 ELSE 0.8 END
                    * CASE WHEN MS.raw_impr_rank < 1 THEN 1 ELSE 0.8 END
                    * (MSS.nlikes + MSS.ndislikes)::float / (MSS.nmemes_sent_events + 1.)
                    * (UMSS.nlikes + 1.)::float / (UMSS.nlikes + UMSS.ndislikes + 1.)
                    * {disliked_source_demote_sql()}
                ) AS score
            FROM meme M
            INNER JOIN meme_stats MS
                ON M.id = MS.meme_id
            INNER JOIN meme_source_stats MSS
                ON MSS.meme_source_id = M.meme_source_id
            INNER JOIN user_meme_source_stats UMSS
                ON UMSS.user_id = :user_id
                AND UMSS.meme_source_id = M.meme_source_id
            WHERE M.status = 'ok'
                AND (MS.nlikes + MS.ndislikes) >= {GOAT_MIN_REACTIONS}
                AND MS.lr_smoothed >= {GOAT_MIN_LR}
                AND M.created_at <= NOW() - INTERVAL '{GOAT_MIN_AGE_DAYS} days'
                AND NOT EXISTS (
                    SELECT 1 FROM user_meme_reaction umr
                    WHERE umr.user_id = :user_id
                      AND umr.meme_id = M.id
                      AND umr.sent_at > NOW() - (:goat_recently_sent_window_days * INTERVAL '1 day')
                )
        )

        SELECT
            M.id
           , M.type, M.telegram_file_id, M.caption
           , 'goat' AS recommended_by
           , COALESCE(SCORES.nlikes, 0) AS nlikes
        FROM meme M
        INNER JOIN SCORES
            ON SCORES.meme_id = M.id

        INNER JOIN user_language L
            ON L.user_id = :user_id
            AND L.language_code = M.language_code

        WHERE 1=1
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}
            {block_disliked_sources_sql_filter()}
        ORDER BY SCORES.score DESC NULLS LAST
        LIMIT :limit
    """
    return await fetch_all(
        text(query),
        _build_params(
            user_id,
            limit,
            exclude_meme_ids,
            goat_recently_sent_window_days=GOAT_RECENTLY_SENT_WINDOW_DAYS,
        ),
    )


async def get_recently_liked(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
):
    query = f"""
        WITH EVENTS AS (
            SELECT *
            FROM user_meme_reaction UMR
            WHERE reaction_id = 1
            ORDER BY sent_at DESC
            LIMIT 10000
        )
        , CANDIDATES AS (
            SELECT meme_id AS id
            FROM EVENTS
            GROUP BY meme_id
            HAVING COUNT(*) > 1
            ORDER BY COUNT(*) DESC
        )

        SELECT
            M.id
            , M.type, M.telegram_file_id, M.caption
            , 'recently_liked' AS recommended_by
            , COALESCE(MS.nlikes, 0) AS nlikes

        FROM CANDIDATES C
        INNER JOIN meme M
            ON M.id = C.id
        LEFT JOIN meme_stats MS
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
            AND R.meme_id IS NULL
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}
            {block_disliked_sources_sql_filter()}
        -- Prefer non-disliked sources first (demote mult 1.0 before 0.15)
        ORDER BY {disliked_source_demote_sql()} DESC, M.id DESC
        LIMIT :limit
    """
    return await fetch_all(text(query), _build_params(user_id, limit, exclude_meme_ids))


async def cold_start_explore(
    user_id: int,
    limit: int = 5,
    exclude_meme_ids: list[int] = [],
    candidate_guardrails_enabled: bool = False,
):
    """Phase 1 cold start: quality-first selection for new user first impression.

    Serves memes with proven social proof (>=20 explicit reactions) and
    positive user-bias-corrected like rate. New users need the bot's best
    content first — maximising per-meme quality gives the best chance of a
    good first impression before Phase 2 adapts to their taste via real
    reactions.

    lr_smoothed is user-bias-corrected and centered around 0 (not a raw
    like rate). A value of 0.10 means the meme is liked ~10pp above what
    each user's personal average would predict — a strong positive signal.
    The previous threshold of 0.40 was far too high and left the pool empty
    because even universally-liked memes rarely exceed ~0.20 after bias
    correction.

    Used for memes 1-5 (first impression).
    """

    query = f"""
        SELECT
            M.id
            , M.type, M.telegram_file_id, M.caption
            , :recommended_by AS recommended_by
            , COALESCE(MS.nlikes, 0) AS nlikes

        FROM meme M
        INNER JOIN meme_stats MS
            ON MS.meme_id = M.id
        INNER JOIN meme_source S
            ON S.id = M.meme_source_id
        INNER JOIN user_language L
            ON L.language_code = M.language_code
            AND L.user_id = :user_id
        LEFT JOIN user_meme_reaction R
            ON R.meme_id = M.id
            AND R.user_id = :user_id

        WHERE 1=1
            AND M.status = 'ok'
            AND R.meme_id IS NULL
            AND (MS.nlikes + MS.ndislikes) >= :cold_start_explore_min_reactions
            AND MS.lr_smoothed >= :cold_start_explore_min_lr_smoothed
            AND (MS.nlikes::float / NULLIF(MS.nlikes + MS.ndislikes, 0))
                >= :cold_start_explore_min_raw_like_rate
            {TEXT_LIGHT_OCR_FILTER_SQL}
            {_cold_start_guardrail_source_filter(candidate_guardrails_enabled)}
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}
            {block_disliked_sources_sql_filter()}

        ORDER BY MS.lr_smoothed DESC NULLS LAST,
                 (MS.nlikes::float / NULLIF(MS.nlikes + MS.ndislikes, 0)) DESC,
                 (MS.nlikes + MS.ndislikes) DESC
        LIMIT :limit
    """
    params = _cold_start_params(
        user_id,
        limit,
        exclude_meme_ids,
        engine=COLD_START_EXPLORE_RECOMMENDED_BY,
        candidate_guardrails_enabled=candidate_guardrails_enabled,
    )
    params.update(
        {
            "cold_start_explore_min_reactions": COLD_START_EXPLORE_MIN_EXPLICIT_REACTIONS,
            "cold_start_explore_min_lr_smoothed": COLD_START_EXPLORE_MIN_LR_SMOOTHED,
            "cold_start_explore_min_raw_like_rate": COLD_START_EXPLORE_MIN_RAW_LIKE_RATE,
        }
    )
    return await fetch_all(text(query), params)


async def cold_start_adapt(
    user_id: int,
    limit: int = 15,
    exclude_meme_ids: list[int] = [],
    candidate_guardrails_enabled: bool = False,
):
    """Phase 2 cold start: adapt to user's reactions in real-time.

    Reads raw user_meme_reaction (bypasses 15-min stats delay) to calculate
    per-source weights. Liked source gets boosted, disliked gets penalized
    (floor weight 0.1 — never zero). Memes ranked by lr_smoothed * source_weight.

    30% exploration: sources with no reactions get neutral weight (0.5).

    Used for memes 6-15 (early personalization).
    """

    query = f"""
        WITH recent_reactions AS (
            SELECT
                M.meme_source_id,
                SUM(CASE WHEN UMR.reaction_id = 1 THEN 1.0 ELSE -0.5 END) AS raw_weight
            FROM (
                SELECT meme_id, reaction_id
                FROM user_meme_reaction
                WHERE user_id = :user_id
                ORDER BY sent_at DESC
                LIMIT 15
            ) UMR
            INNER JOIN meme M ON M.id = UMR.meme_id
            GROUP BY M.meme_source_id
        )
        SELECT
            M.id
            , M.type, M.telegram_file_id, M.caption
            , :recommended_by AS recommended_by
            , COALESCE(MS.nlikes, 0) AS nlikes

        FROM meme M
        INNER JOIN meme_stats MS
            ON MS.meme_id = M.id
        INNER JOIN meme_source S
            ON S.id = M.meme_source_id

        INNER JOIN user_language L
            ON L.language_code = M.language_code
            AND L.user_id = :user_id

        LEFT JOIN user_meme_reaction R
            ON R.meme_id = M.id
            AND R.user_id = :user_id

        LEFT JOIN recent_reactions RR
            ON RR.meme_source_id = M.meme_source_id

        WHERE 1=1
            AND M.status = 'ok'
            AND R.meme_id IS NULL
            AND MS.nlikes > 1
            AND MS.nmemes_sent >= 10
            {TEXT_LIGHT_OCR_FILTER_SQL}
            {_cold_start_guardrail_source_filter(candidate_guardrails_enabled)}
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}
            {block_disliked_sources_sql_filter()}

        ORDER BY -1
            * GREATEST(COALESCE(RR.raw_weight, 0) + 0.5, 0.1)
            * MS.lr_smoothed
        LIMIT :limit
    """
    return await fetch_all(
        text(query),
        _cold_start_params(
            user_id,
            limit,
            exclude_meme_ids,
            engine=COLD_START_ADAPT_RECOMMENDED_BY,
            candidate_guardrails_enabled=candidate_guardrails_enabled,
        ),
    )


async def viral_shares(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
):
    """Memes with proven share-click conversion (unique non-self deep-link clickers).

    Ranks by invited_count / ln(nmemes_sent + e) so high-volume memes do not
    dominate purely by raw share-click counts. Quality floor keeps junk out of
    the growth-oriented blend slot.
    """
    query = f"""
        SELECT
            M.id
            , M.type, M.telegram_file_id, M.caption
            , 'viral_shares' AS recommended_by
            , COALESCE(MS.nlikes, 0) AS nlikes
            , COALESCE(MS.invited_count, 0) AS invited_count
            , COALESCE(MS.nmemes_sent, 0) AS nmemes_sent
            , COALESCE(MS.lr_smoothed, 0) AS lr_smoothed
            , (
                COALESCE(MS.invited_count, 0)::float
                / LN(COALESCE(MS.nmemes_sent, 0) + 2.718281828)
              ) AS virality_score

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
            AND R.meme_id IS NULL
            AND COALESCE(MS.invited_count, 0) > 0
            AND COALESCE(MS.nmemes_sent, 0) >= 20
            AND COALESCE(MS.lr_smoothed, 0) >= 0.05
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}
            {block_disliked_sources_sql_filter()}

        ORDER BY
            (
                COALESCE(MS.invited_count, 0)::float
                / LN(COALESCE(MS.nmemes_sent, 0) + 2.718281828)
            ) * {disliked_source_demote_sql()} DESC
            , MS.lr_smoothed DESC NULLS LAST
            , MS.nlikes DESC NULLS LAST
        LIMIT :limit
    """
    return await fetch_all(text(query), _build_params(user_id, limit, exclude_meme_ids))


class CandidatesRetriever:
    """CandidatesRetriever class is used for unit testing"""

    engine_map = {
        "best_uploaded_memes": best_uploaded_memes,
        "lr_smoothed": get_lr_smoothed,
        "text_light_lr_smoothed": get_text_light_lr_smoothed,
        "like_spread_and_recent_memes": like_spread_and_recent_memes,
        "recently_liked": get_recently_liked,
        "goat": goat,
        "es_ranked": get_es_ranked,
        "cold_start_explore": cold_start_explore,
        "cold_start_adapt": cold_start_adapt,
        "viral_shares": viral_shares,
    }

    async def get_candidates(
        self,
        engine: str,
        user_id: int,
        limit: int = 10,
        exclude_mem_ids: list[int] = [],
        **kwargs,
    ) -> list[dict[str, Any]]:
        if engine not in self.engine_map:
            raise ValueError(f"engine {engine} is not supported")

        return await self.engine_map[engine](user_id, limit, exclude_mem_ids, **kwargs)

    async def get_candidates_dict(
        self,
        engines: list[str],
        user_id: int,
        limit: int = 10,
        exclude_mem_ids: list[int] = [],
    ) -> dict[str, list[dict[str, Any]]]:
        tasks = {
            engine: self.get_candidates(engine, user_id, limit, exclude_mem_ids)
            for engine in engines
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        out: dict[str, list[dict[str, Any]]] = {}
        for engine, result in zip(engines, results):
            if isinstance(result, BaseException):
                logger.warning("engine %s failed for user %d", engine, user_id, exc_info=result)
                out[engine] = []
            else:
                out[engine] = result
        return out
