from typing import Any

from sqlalchemy import text

from src.database import fetch_all
from src.recommendations.utils import exclude_meme_ids_sql_filter


# "lr" - like rate
# I'm not sure about the naming, will change later
async def sorted_by_user_source_lr_meme_lr_meme_age(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
) -> list[dict[str, Any]]:
    query = f"""
        SELECT
            M.id, M.type, M.telegram_file_id, M.caption,
            'sorted_by_user_source_lr_meme_lr_meme_age' as recommended_by
        FROM meme M
        LEFT JOIN user_meme_reaction R
            ON R.user_id = {user_id}
            AND R.meme_id = M.id
        INNER JOIN user_language L
            ON L.language_code = M.language_code
            AND L.user_id = {user_id}

		LEFT JOIN user_meme_source_stats UMSS
            ON UMSS.meme_source_id = M.meme_source_id
            AND UMSS.user_id = {user_id}
        LEFT JOIN meme_stats MS
            ON MS.meme_id = M.id

        WHERE 1=1
            AND M.status = 'ok'
            AND R.meme_id IS NULL
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}

        ORDER BY -1
            * COALESCE((UMSS.nlikes + 1.) / (UMSS.nlikes + UMSS.ndislikes + 1), 0.5)
            * COALESCE((MS.nlikes + 1.) / (MS.nlikes + MS.ndislikes + 1), 0.5)
            * CASE WHEN MS.raw_impr_rank < 1 THEN 1 ELSE 0.5 END
            * CASE WHEN MS.age_days < 5 THEN 1 ELSE 0.5 END
            * CASE WHEN M.caption IS NULL THEN 1 ELSE 0.8 END
            * CASE
                WHEN MS.nmemes_sent <= 1 THEN 1
                ELSE (MS.nlikes + MS.ndislikes) * 1. / MS.nmemes_sent
            END

        LIMIT {limit}
    """
    res = await fetch_all(text(query))
    return res


# like rate: 24%
async def most_liked(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
) -> list[dict[str, Any]]:
    query = f"""
        SELECT
            M.id, M.type, M.telegram_file_id, M.caption,
            'most_liked' as recommended_by
        FROM meme M
        LEFT JOIN user_meme_reaction R
            ON R.user_id = {user_id}
            AND R.meme_id = M.id

        INNER JOIN user_language L
            ON L.language_code = M.language_code
            AND L.user_id = {user_id}

        LEFT JOIN meme_stats MS
            ON MS.meme_id = M.id

        WHERE 1=1
            AND M.status = 'ok'
            AND R.meme_id IS NULL
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}

        ORDER BY -1
            * COALESCE((MS.nlikes + 1.) / (MS.nlikes + MS.ndislikes + 1), 0.5)
            * CASE WHEN MS.raw_impr_rank <= 1 THEN 1 ELSE 0.8 END
            * CASE WHEN MS.age_days < 5 THEN 1 ELSE 0.8 END
            * CASE
                WHEN MS.nmemes_sent <= 1 THEN 1
                ELSE (MS.nlikes + MS.ndislikes) * 1. / MS.nmemes_sent
            END

        LIMIT {limit}
    """
    res = await fetch_all(text(query))
    return res


async def multiply_all_scores(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
) -> list[dict[str, Any]]:
    query = f"""
        SELECT
            M.id, M.type, M.telegram_file_id, M.caption,
            'multiply_all_scores' as recommended_by
        --    M.id
        --    , (UMSS.nlikes + 1.) / (UMSS.nlikes + UMSS.ndislikes + 1) user_source
        --    , (MSS.nlikes + 1.) / (MSS.nlikes + MSS.ndislikes + 1) meme_source
        --    , (MS.nlikes + 1.) / (MS.nlikes + MS.ndislikes + 1) meme
        --    , raw_impr_rank
        --    , MS.age_days
        --    , (MS.nlikes + MS.ndislikes) * 1. / MS.nmemes_sent meme_click_rate
        FROM meme M
        LEFT JOIN user_meme_reaction R
            ON R.meme_id = M.id
            AND R.user_id = {user_id}
        INNER JOIN user_language L
            ON L.language_code = M.language_code
            AND L.user_id = {user_id}

        LEFT JOIN user_meme_source_stats UMSS
            ON UMSS.meme_source_id = M.meme_source_id
            AND UMSS.user_id = {user_id}
        LEFT JOIN meme_stats MS
            ON MS.meme_id = M.id
        LEFT JOIN meme_source_stats MSS
            ON MSS.meme_source_id = M.meme_source_id

        WHERE 1=1
            AND M.status = 'ok'
            AND R.meme_id IS NULL -- not seen
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}

        ORDER BY -1
            * COALESCE((UMSS.nlikes + 1.) / (UMSS.nlikes + UMSS.ndislikes + 1), 0.5)
            * COALESCE((MSS.nlikes + 1.) / (MSS.nlikes + MSS.ndislikes + 1) , 0.5)
            * COALESCE((MS.nlikes + 1.) / (MS.nlikes + MS.ndislikes + 1), 0.5)
            * CASE WHEN MS.raw_impr_rank < 1 THEN 1 ELSE 0.5 END
            * CASE WHEN MS.age_days < 5 THEN 1 ELSE 0.5 END
            * CASE WHEN M.caption IS NULL THEN 1 ELSE 0.8 END
            * CASE
                WHEN MS.nmemes_sent <= 1 THEN 1
                ELSE (MS.nlikes + MS.ndislikes) * 1. / MS.nmemes_sent
            END

        LIMIT {limit}
    """
    res = await fetch_all(text(query))
    return res


async def less_seen_meme_and_source(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
) -> list[dict[str, Any]]:
    query = f"""
        WITH LESS_SEEN_MEME_FROM_EACH_SOURCE AS (
            SELECT DISTINCT ON (M.meme_source_id)
                M.id, M.type, M.telegram_file_id, M.caption,
                'less_seen_meme_and_source' as recommended_by

                , M.meme_source_id
                , COALESCE(MS.nmemes_sent, 0) meme_sent_times
                , COALESCE(UMSS.nlikes + UMSS.ndislikes, 0) source_seen_times
            FROM meme M
            LEFT JOIN user_meme_reaction R
                ON R.user_id = {user_id}
                AND R.meme_id = M.id

            INNER JOIN user_language L
                ON L.language_code = M.language_code
                AND L.user_id = {user_id}

            LEFT JOIN meme_stats MS
                ON MS.meme_id = M.id

            LEFT JOIN user_meme_source_stats UMSS
                ON UMSS.meme_source_id = M.meme_source_id
                AND UMSS.user_id = {user_id}

            WHERE 1=1
                AND M.status = 'ok'
                AND R.meme_id IS NULL
                {exclude_meme_ids_sql_filter(exclude_meme_ids)}

            ORDER BY
                M.meme_source_id, -- one meme from each source
                meme_sent_times
        )

        SELECT
            id, type, telegram_file_id, caption, recommended_by
        FROM LESS_SEEN_MEME_FROM_EACH_SOURCE
        ORDER BY source_seen_times -- less seen sources
        LIMIT {limit}
    """
    res = await fetch_all(text(query))
    return res


# like rate: 38%
async def top_memes_from_less_seen_sources(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
) -> list[dict[str, Any]]:
    query = f"""
        WITH LESS_SEEN_SOURCES AS (
            SELECT
                MS.id,
                COALESCE(UMSS.nlikes + UMSS.ndislikes, 0) / 10 seen_times
            FROM meme_source MS
            LEFT JOIN user_meme_source_stats UMSS
                ON MS.id = UMSS.meme_source_id
                AND UMSS.user_id = {user_id}
            ORDER BY seen_times
        )

        SELECT
            M.id
            , M.type, M.telegram_file_id
            , M.caption, M.recommended_by

        FROM (
            SELECT DISTINCT ON (M.meme_source_id)
                M.id, M.type, M.telegram_file_id, M.caption,
                'less_seen_sources' as recommended_by,

                1
                    * CASE WHEN MS.raw_impr_rank <= 1 THEN 1 ELSE 0.5 END
                    * CASE WHEN MS.age_days < 5 THEN 1 ELSE 0.5 END
                    * COALESCE((MS.nlikes+1.) / (MS.nlikes+MS.ndislikes+1), 0.5)
                    * COALESCE((MSS.nlikes+1.) / (MSS.nlikes+MSS.ndislikes+1), 0.5)
                AS score,
                M.meme_source_id

            FROM meme M

            LEFT JOIN user_meme_reaction R
                ON R.meme_id = M.id
                AND R.user_id = {user_id}

            INNER JOIN user_language L
                ON L.user_id = {user_id}
                AND L.language_code = M.language_code

            LEFT JOIN meme_stats MS
                ON MS.meme_id = M.id

            LEFT JOIN meme_source_stats MSS
                ON MSS.meme_source_id = M.meme_source_id

            WHERE 1=1
                AND M.status = 'ok'
                AND R.meme_id IS NULL
                {exclude_meme_ids_sql_filter(exclude_meme_ids)}

            ORDER BY M.meme_source_id, score
        ) M
        INNER JOIN LESS_SEEN_SOURCES
            ON LESS_SEEN_SOURCES.id = M.meme_source_id
        ORDER BY seen_times, score DESC
        LIMIT {limit}

    """
    res = await fetch_all(text(query))
    return res


async def classic(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
):
    query = f"""
        SELECT
            M.id
            , M.type, M.telegram_file_id, M.caption
            , 'classic' AS recommended_by

        FROM meme M
        INNER JOIN meme_stats MS
            ON MS.meme_id = M.id

        INNER JOIN user_language L
            ON L.language_code = M.language_code
            AND L.user_id = {user_id}

        LEFT JOIN user_meme_reaction R
            ON R.meme_id = M.id
            AND R.user_id = {user_id}

        LEFT JOIN user_meme_source_stats UMSS
            ON UMSS.meme_source_id = M.meme_source_id
            AND UMSS.user_id = {user_id}

        WHERE 1=1
            AND M.status = 'ok'
            AND R.meme_id IS NULL
            AND MS.nlikes > 1
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}

        ORDER BY -1
            * (UMSS.nlikes + 1.) / (UMSS.nlikes + UMSS.ndislikes + 1.)
            * (MS.nlikes + 1.) / (MS.nlikes + MS.ndislikes + 1.)
        LIMIT {limit}
    """
    res = await fetch_all(text(query))
    return res


async def uploaded_memes(
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
            AND L.user_id = {user_id}

        LEFT JOIN user_meme_reaction R
            ON R.meme_id = M.id
            AND R.user_id = {user_id}

        LEFT JOIN user_meme_source_stats UMSS
            ON UMSS.meme_source_id = M.meme_source_id
            AND UMSS.user_id = {user_id}

        WHERE 1=1
            AND M.status = 'ok'
            AND R.meme_id IS NULL
            AND S.type = 'user upload'
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}

        ORDER BY -1
            * (UMSS.nlikes + 1.) / (UMSS.nlikes + UMSS.ndislikes + 1.)
            * (MS.nlikes + 1.) / (MS.nlikes + MS.ndislikes + 1.)
        NULLS FIRST
        LIMIT {limit}
    """
    res = await fetch_all(text(query))
    return res


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

            -- , MS.nlikes, MS.ndislikes
        FROM meme M
        INNER JOIN meme_stats MS
            ON MS.meme_id = M.id

        INNER JOIN user_language L
            ON L.user_id = {user_id}
            AND L.language_code = M.language_code

        LEFT JOIN user_meme_reaction R
                ON R.meme_id = M.id
                AND R.user_id = {user_id}

        WHERE 1=1
            AND M.status = 'ok'
            AND R.meme_id IS NULL

            AND MS.nlikes > MS.ndislikes
            AND MS.raw_impr_rank = 0
            AND age_days < 30
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}
        ORDER BY -1
            * (MS.nlikes - MS.ndislikes) / (MS.nmemes_sent + 1.)
            * CASE WHEN MS.age_days < 30 THEN 1 ELSE 0.5 END
        LIMIT {limit}
    """
    res = await fetch_all(text(query))
    return res


async def get_best_memes_from_each_source(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
) -> list[dict[str, Any]]:
    query = f"""
        SELECT
            M.id
            , M.type, M.telegram_file_id, M.caption, M.recommended_by
        FROM (
            SELECT DISTINCT ON (M.meme_source_id)
                M.id, M.type, M.telegram_file_id, M.caption,
                'best_meme_from_each_source' as recommended_by,

                1
                    * CASE WHEN MS.raw_impr_rank <= 1 THEN 1 ELSE 0.8 END
                    * CASE WHEN MS.age_days < 14 THEN 1 ELSE 0.8 END
                    * COALESCE((MS.nlikes+1.) / (MS.nlikes+MS.ndislikes+1), 0.5)
                    * CASE
                        WHEN MS.nmemes_sent <= 1 THEN 1
                        ELSE (MS.nlikes + MS.ndislikes) * 1. / MS.nmemes_sent
                    END
                AS score

            FROM meme M
            LEFT JOIN user_meme_reaction R
                ON R.meme_id = M.id
                AND R.user_id = {user_id}

            INNER JOIN user_language L
                ON L.user_id = {user_id}
                AND L.language_code = M.language_code

            LEFT JOIN meme_stats MS
                ON MS.meme_id = M.id

            WHERE 1=1
                AND M.status = 'ok'
                AND R.meme_id IS NULL
                AND MS.nlikes > 0
                AND (MS.nlikes) / (MS.nlikes+MS.ndislikes) > 0.2
                AND MS.sec_to_react < 20
                {exclude_meme_ids_sql_filter(exclude_meme_ids)}
            ORDER BY M.meme_source_id, score DESC
        ) M
        ORDER BY score DESC
        LIMIT {limit}
    """
    res = await fetch_all(text(query))
    return res
