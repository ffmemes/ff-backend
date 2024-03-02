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
            * COALESCE((UMSS.nlikes + 1) / (UMSS.nlikes + UMSS.ndislikes + 1), 0.5)
            * COALESCE((MS.nlikes + 1) / (MS.nlikes + MS.ndislikes + 1), 0.5)
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
