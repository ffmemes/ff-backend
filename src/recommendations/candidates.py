import asyncio
from typing import Any

from sqlalchemy import text

from src.database import fetch_all
from src.recommendations.utils import exclude_meme_ids_sql_filter


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

        ORDER BY -1
            * COALESCE((UMSS.nlikes + 1.) / (UMSS.nlikes + UMSS.ndislikes + 1.), 0.5)
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

        FROM meme M
        INNER JOIN meme_stats MS
            ON MS.meme_id = M.id

        INNER JOIN user_language L
            ON L.user_id = :user_id
            AND L.language_code = M.language_code

        LEFT JOIN user_meme_reaction R
                ON R.meme_id = M.id
                AND R.user_id = :user_id

        WHERE 1=1
            AND M.status = 'ok'
            AND R.meme_id IS NULL

            AND MS.nlikes > MS.ndislikes
            AND MS.raw_impr_rank = 0
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}
        ORDER BY -1
            * (MS.nlikes - MS.ndislikes) / (MS.nmemes_sent + 1.)
        LIMIT :limit
    """
    return await fetch_all(text(query), _build_params(user_id, limit, exclude_meme_ids))


async def get_lr_smoothed(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
    min_sends: int = 0,
):
    """
    Uses the following score to rank memes

    score = Like Rate Smoothed * User-Source Like Rate

    Args:
        min_sends: minimum nmemes_sent to filter for statistical confidence.
            Use min_sends=10 for cold start to ensure battle-tested memes.
    """

    min_sends_filter = "AND MS.nmemes_sent >= :min_sends" if min_sends > 0 else ""

    query = f"""
        SELECT
            M.id
            , M.type, M.telegram_file_id, M.caption
            , 'lr_smoothed' AS recommended_by

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
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}

        ORDER BY -1
            * COALESCE((UMSS.nlikes + 1.) / (UMSS.nlikes + UMSS.ndislikes + 1.), 0.5)
            * MS.lr_smoothed
        LIMIT :limit
    """
    params = _build_params(user_id, limit, exclude_meme_ids)
    if min_sends > 0:
        params["min_sends"] = int(min_sends)
    return await fetch_all(text(query), params)


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

        ORDER BY -1
            * COALESCE((UMSS.nlikes + 1.) / (UMSS.nlikes + UMSS.ndislikes + 1.), 0.5)
            * MS.engagement_score
        LIMIT :limit
    """
    return await fetch_all(text(query), _build_params(user_id, limit, exclude_meme_ids))


async def goat(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
):
    query = f"""
        WITH SCORES AS (
            SELECT
                MS.meme_id,
                1.0
                    * (MS.nlikes - MS.ndislikes)::float / (MS.nmemes_sent + 1)
                    * MS.lr_smoothed
                    * (MS.nlikes + MS.ndislikes)::float / (MS.nmemes_sent + 1)
                    * CASE WHEN MS.sec_to_react BETWEEN 2 AND 10 THEN 1 ELSE 0.6 END
                    * CASE WHEN MS.invited_count > 0 THEN 1 ELSE 0.8 END
                    * CASE WHEN MS.raw_impr_rank < 1 THEN 1 ELSE 0.8 END
                    * (MSS.nlikes + MSS.ndislikes)::float / (MSS.nmemes_sent_events + 1.)
                    * (UMSS.nlikes + 1.)::float / (UMSS.nlikes + UMSS.ndislikes + 1.)
                AS score
            FROM meme M
            INNER JOIN meme_stats MS
                ON M.id = MS.meme_id
            INNER JOIN meme_source_stats MSS
                ON MSS.meme_source_id = M.meme_source_id
            INNER JOIN user_meme_source_stats UMSS
                ON UMSS.user_id = :user_id
                AND UMSS.meme_source_id = M.meme_source_id
            WHERE M.status = 'ok'
        )


        SELECT
            M.id
           , M.type, M.telegram_file_id, M.caption
           , 'goat' AS recommended_by
        FROM meme M
        INNER JOIN SCORES
            ON SCORES.meme_id = M.id

        INNER JOIN user_language L
            ON L.user_id = :user_id
            AND L.language_code = M.language_code

        LEFT JOIN user_meme_reaction R
                ON R.meme_id = M.id
                AND R.user_id = :user_id
                AND R.sent_at > NOW() - INTERVAL '30 days'

        WHERE 1=1
            AND R.meme_id IS NULL
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}
        ORDER BY SCORES.score DESC NULLS LAST
        LIMIT :limit
    """
    return await fetch_all(text(query), _build_params(user_id, limit, exclude_meme_ids))


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

        FROM CANDIDATES C
        INNER JOIN meme M
            ON M.id = C.id

        INNER JOIN user_language L
            ON L.language_code = M.language_code
            AND L.user_id = :user_id

        LEFT JOIN user_meme_reaction R
            ON R.meme_id = M.id
            AND R.user_id = :user_id

        WHERE 1=1
            AND M.status = 'ok'
            AND R.meme_id IS NULL
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}
        LIMIT :limit
    """
    return await fetch_all(text(query), _build_params(user_id, limit, exclude_meme_ids))


async def cold_start_explore(
    user_id: int,
    limit: int = 15,
    exclude_meme_ids: list[int] = [],
):
    """Phase 1 cold start: globally top-quality memes by like rate.

    Serves the highest lr_smoothed memes overall — no source-diversity
    constraint. For new users with no preference data, maximising per-meme
    quality gives the best chance of a good first impression regardless of
    genre. The adapt phase (memes 6-15) then calibrates on real reactions.

    Used for memes 1-5 (first impression).
    """

    query = f"""
        SELECT
            M.id
            , M.type, M.telegram_file_id, M.caption
            , 'cold_start_explore' AS recommended_by

        FROM meme M
        INNER JOIN meme_stats MS
            ON MS.meme_id = M.id
        INNER JOIN user_language L
            ON L.language_code = M.language_code
            AND L.user_id = :user_id
        LEFT JOIN user_meme_reaction R
            ON R.meme_id = M.id
            AND R.user_id = :user_id

        WHERE 1=1
            AND M.status = 'ok'
            AND R.meme_id IS NULL
            AND MS.nmemes_sent >= 20
            AND MS.lr_smoothed > 0.45
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}

        ORDER BY MS.lr_smoothed DESC
        LIMIT :limit
    """
    return await fetch_all(text(query), _build_params(user_id, limit, exclude_meme_ids))


async def cold_start_adapt(
    user_id: int,
    limit: int = 15,
    exclude_meme_ids: list[int] = [],
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
            , 'cold_start_adapt' AS recommended_by

        FROM meme M
        INNER JOIN meme_stats MS
            ON MS.meme_id = M.id

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
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}

        ORDER BY -1
            * GREATEST(COALESCE(RR.raw_weight, 0) + 0.5, 0.1)
            * MS.lr_smoothed
        LIMIT :limit
    """
    return await fetch_all(text(query), _build_params(user_id, limit, exclude_meme_ids))


class CandidatesRetriever:
    """CandidatesRetriever class is used for unit testing"""

    engine_map = {
        "best_uploaded_memes": best_uploaded_memes,
        "lr_smoothed": get_lr_smoothed,
        "like_spread_and_recent_memes": like_spread_and_recent_memes,
        "recently_liked": get_recently_liked,
        "goat": goat,
        "es_ranked": get_es_ranked,
        "cold_start_explore": cold_start_explore,
        "cold_start_adapt": cold_start_adapt,
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
        results = await asyncio.gather(*tasks.values())
        return dict(zip(engines, results))
