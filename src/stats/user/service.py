from typing import Any
from datetime import datetime
from sqlalchemy import select, nulls_first, text
from sqlalchemy.dialects.postgresql import insert

from src.database import (
    language,
    meme,
    meme_source,
    meme_raw_telegram,
    meme_raw_vk,
    execute, fetch_one, fetch_all,
)


async def calculate_user_stats() -> None:
    # TODO: update only recently active users
    # TODO: index on reaction_id?
    insert_query = f"""
        WITH EVENTS AS (
            SELECT 
                *,
                reacted_at - LAG(reacted_at) OVER (PARTITION BY user_id ORDER BY reacted_at) AS lag
            FROM user_meme_reaction
        )

        INSERT INTO user_stats (
            user_id, 
            nlikes, 
            ndislikes, 
            nmemes_sent, 
            nsessions, 
            active_days_count,
            updated_at
        )
        SELECT 
            user_id
            , COUNT(*) FILTER (WHERE reaction_id = 1) nlikes
            , COUNT(*) FILTER (WHERE reaction_id = 2) ndislikes
            , COUNT(*) nmemes_sent
            , COUNT(*) FILTER (WHERE lag > INTERVAL '2 hours') nsessions
            , COUNT(DISTINCT DATE(reacted_at)) AS active_days_count
            , NOW() AS updated_at
        FROM EVENTS
        GROUP BY 1
        HAVING MAX(reacted_at) > NOW() - INTERVAL '1 day'
        ON CONFLICT (user_id) DO 
        UPDATE SET
            nlikes = EXCLUDED.nlikes,
            ndislikes = EXCLUDED.ndislikes,
            nsessions = EXCLUDED.nsessions,
            active_days_count = EXCLUDED.active_days_count,
            updated_at = EXCLUDED.updated_at
    """
    await execute(text(insert_query))
