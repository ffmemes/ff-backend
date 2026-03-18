import logging

from sqlalchemy import text

from src.database import execute

# Shared SQL template for user-meme-source stats.
# {user_filter} is "WHERE R.user_id = :user_id" for single-user or "" for batch.
_USER_MEME_SOURCE_STATS_SQL = """
    INSERT INTO user_meme_source_stats (
        user_id,
        meme_source_id,
        nlikes,
        ndislikes,
        updated_at
    )
    SELECT
        R.user_id,
        M.meme_source_id,
        COUNT(*) FILTER (WHERE reaction_id = 1) nlikes,
        COUNT(*) FILTER (WHERE reaction_id = 2) ndislikes,
        NOW() AS updated_at
    FROM user_meme_reaction R
    INNER JOIN meme M
        ON M.id = R.meme_id
    WHERE reaction_id IS NOT NULL
    {user_filter}
    GROUP BY 1,2
    ON CONFLICT (user_id, meme_source_id) DO
    UPDATE SET
        nlikes = EXCLUDED.nlikes,
        ndislikes = EXCLUDED.ndislikes,
        updated_at = EXCLUDED.updated_at
"""


async def update_single_user_meme_source_stats(user_id: int) -> None:
    """Tier 1: Recompute source stats for a single user (called inline on reaction).

    Best-effort: silently catches deadlocks since Tier 2 batch will catch up.
    """
    try:
        query = _USER_MEME_SOURCE_STATS_SQL.format(
            user_filter="AND R.user_id = :user_id",
        )
        await execute(text(query), {"user_id": user_id})
    except Exception:
        logging.debug(f"Tier 1 user_meme_source_stats skipped for user {user_id} (likely deadlock)")


async def calculate_user_meme_source_stats() -> None:
    """Tier 2: Batch recompute source stats for all users with reactions."""
    query = _USER_MEME_SOURCE_STATS_SQL.format(user_filter="")
    await execute(text(query))
