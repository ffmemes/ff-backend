from typing import Any
from sqlalchemy import text

from src.database import fetch_all
from src.recommendations.utils import exclude_meme_ids_sql_filter


async def get_best_memes_from_each_source(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
) -> list[dict[str, Any]]:
    query = f"""
        SELECT 
            M.id, M.type, M.telegram_file_id, M.caption,
            'cold_start' as recommended_by
        FROM (
            SELECT DISTINCT ON (M.meme_source_id)
                M.id, M.type, M.telegram_file_id, M.caption,
                'cold_start' as recommended_by,
                
                1
                    * COALESCE((MS.nlikes + 1) / (MS.ndislikes + 1), 0.5)
                    * COALESCE(age_days * (-1), 0.1)
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
                {exclude_meme_ids_sql_filter(exclude_meme_ids)}
            ORDER BY M.meme_source_id, score
        ) M
        ORDER BY score DESC
        LIMIT {limit}
    """
    res = await fetch_all(text(query))
    return res

