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
            time_spent_sec,
            first_reaction_at,
            last_reaction_at,
            updated_at
        )
        SELECT
            user_id
            , COUNT(*) FILTER (WHERE reaction_id = 1) nlikes
            , COUNT(*) FILTER (WHERE reaction_id = 2) ndislikes
            , COUNT(*) nmemes_sent
            , COUNT(*) FILTER (WHERE lag > INTERVAL '1 hours') + 1 nsessions
            , COUNT(DISTINCT DATE(reacted_at)) AS active_days_count
            , COALESCE(EXTRACT(EPOCH FROM SUM(lag) FILTER (WHERE lag < INTERVAL '2 minutes'))::INT, 0) time_spent_sec
            , MIN(reacted_at) first_reaction_at
            , MAX(reacted_at) last_reaction_at
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
            time_spent_sec = EXCLUDED.time_spent_sec,
            first_reaction_at = EXCLUDED.first_reaction_at,
            last_reaction_at = EXCLUDED.last_reaction_at,
            updated_at = EXCLUDED.updated_at
    """  # noqa: E501
    await execute(text(insert_query))


async def calculate_inviter_stats():
    insert_query = """
        WITH INVITED_USERS_STATS AS (
            SELECT
                inviter_id, COUNT(*) invited_users
            FROM "user"
            WHERE inviter_id IS NOT NULL
            GROUP BY 1
        )

        UPDATE user_stats
        SET invited_users = INVITED_USERS_STATS.invited_users
        FROM INVITED_USERS_STATS
        WHERE
            user_stats.user_id = INVITED_USERS_STATS.inviter_id
    """
    await execute(text(insert_query))
