import logging

from sqlalchemy import text

from src.database import execute

# Shared SQL template for user stats computation.
# The {user_filter} placeholder is replaced with either:
#   - "WHERE user_id = :user_id" for single-user (Tier 1)
#   - "" for batch (Tier 2, processes all then filters at HAVING)
_USER_STATS_SQL = """
    WITH EVENTS AS (
        SELECT
            *,
            reacted_at - LAG(reacted_at)
                OVER (PARTITION BY user_id ORDER BY reacted_at)
            AS lag,
            CASE WHEN
                reacted_at - LAG(reacted_at)
                    OVER (PARTITION BY user_id ORDER BY reacted_at)
                > INTERVAL '30 minutes'
                OR LAG(reacted_at)
                    OVER (PARTITION BY user_id ORDER BY reacted_at)
                IS NULL
            THEN 1 ELSE 0 END AS is_new_session
        FROM user_meme_reaction
        {user_filter}
    ),

    SESSION_IDS AS (
        SELECT *,
            SUM(is_new_session) OVER (
                PARTITION BY user_id ORDER BY reacted_at
            ) AS session_id
        FROM EVENTS
    ),

    SESSION_LENGTHS AS (
        SELECT
            user_id,
            session_id,
            COUNT(*) AS memes_in_session
        FROM SESSION_IDS
        GROUP BY user_id, session_id
        HAVING COUNT(*) >= 2
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
        median_session_length,
        updated_at
    )
    SELECT
        E.user_id
        , COUNT(*) FILTER (WHERE reaction_id = 1) nlikes
        , COUNT(*) FILTER (WHERE reaction_id = 2) ndislikes
        , COUNT(*) nmemes_sent
        , COUNT(*) FILTER (WHERE lag > INTERVAL '30 minutes') + 1 nsessions
        , COUNT(DISTINCT DATE(reacted_at)) AS active_days_count
        , COALESCE(EXTRACT(EPOCH FROM SUM(lag) FILTER (WHERE lag < INTERVAL '2 minutes'))::INT, 0) time_spent_sec
        , MIN(reacted_at) first_reaction_at
        , MAX(reacted_at) last_reaction_at
        , COALESCE(SL.median_session_length, 0) median_session_length
        , NOW() AS updated_at
    FROM EVENTS E
    LEFT JOIN (
        SELECT
            user_id,
            (percentile_cont(0.5) WITHIN GROUP (ORDER BY memes_in_session))::INT
                AS median_session_length
        FROM SESSION_LENGTHS
        GROUP BY user_id
    ) SL ON SL.user_id = E.user_id
    GROUP BY E.user_id, SL.median_session_length
    {having_filter}
    ORDER BY E.user_id
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
        median_session_length = EXCLUDED.median_session_length,
        updated_at = EXCLUDED.updated_at
"""  # noqa: E501


async def update_single_user_stats(user_id: int) -> None:
    """Tier 1: Recompute stats for a single user (called inline on reaction).

    Best-effort: silently catches deadlocks since Tier 2 batch will catch up.
    """
    try:
        query = _USER_STATS_SQL.format(
            user_filter="WHERE user_id = :user_id",
            having_filter="",
        )
        await execute(text(query), {"user_id": user_id})
    except Exception:
        logging.debug(f"Tier 1 user_stats skipped for user {user_id} (likely deadlock)")


async def calculate_user_stats() -> None:
    """Tier 2: Batch recompute stats for recently active users.

    Scans the full table but only upserts users who reacted in the last day.
    With Tier 1 handling inline updates, this serves as a consistency catch-up.
    """
    query = _USER_STATS_SQL.format(
        user_filter="",
        having_filter="HAVING MAX(reacted_at) > NOW() - INTERVAL '1 day'",
    )
    await execute(text(query))


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
