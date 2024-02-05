from sqlalchemy import text

from src.database import execute


async def calculate_user_stats() -> None:
    # TODO: update only recently active users
    # TODO: index on reaction_id?
    insert_query = """
        WITH EVENTS AS (
            SELECT
                *,
                reacted_at - LAG(reacted_at)
                    OVER (PARTITION BY user_id ORDER BY reacted_at)
                AS lag
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
            , COUNT(*) FILTER (WHERE lag > INTERVAL '2 hours') + 1 nsessions
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
            nmemes_sent = EXCLUDED.nmemes_sent,
            active_days_count = EXCLUDED.active_days_count,
            updated_at = EXCLUDED.updated_at
    """
    await execute(text(insert_query))
