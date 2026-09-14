from collections.abc import Collection

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from src.database import run_in_transaction


async def refresh_user_meme_source_stats_on_connection(
    conn: AsyncConnection,
    *,
    user_ids: Collection[int],
    meme_source_ids: Collection[int],
) -> None:
    """Recompute a small, known set of user/source preference rows.

    Duplicate resolution changes historic reactions outside the seven-day
    batch window.  Rebuild only the users whose duplicate-side history was
    removed and the two sources involved in that merge, including deletion of
    rows which no longer have an explicit reaction.
    """
    affected_user_ids = list(set(user_ids))
    affected_source_ids = list(set(meme_source_ids))
    if not affected_user_ids or not affected_source_ids:
        return

    params = {
        "user_ids": affected_user_ids,
        "meme_source_ids": affected_source_ids,
    }
    await conn.execute(
        text(
            """
            DELETE FROM user_meme_source_stats stats
            WHERE stats.user_id = ANY(:user_ids)
              AND stats.meme_source_id = ANY(:meme_source_ids)
              AND NOT EXISTS (
                  SELECT 1
                  FROM user_meme_reaction reaction
                  INNER JOIN meme
                      ON meme.id = reaction.meme_id
                  WHERE reaction.user_id = stats.user_id
                    AND meme.meme_source_id = stats.meme_source_id
                    AND reaction.reaction_id IS NOT NULL
              )
            """
        ),
        params,
    )
    await conn.execute(
        text(
            """
            INSERT INTO user_meme_source_stats (
                user_id,
                meme_source_id,
                nlikes,
                ndislikes,
                updated_at
            )
            SELECT
                reaction.user_id,
                meme.meme_source_id,
                COUNT(*) FILTER (WHERE reaction.reaction_id = 1),
                COUNT(*) FILTER (WHERE reaction.reaction_id = 2),
                NOW()
            FROM user_meme_reaction reaction
            INNER JOIN meme
                ON meme.id = reaction.meme_id
            WHERE reaction.user_id = ANY(:user_ids)
              AND meme.meme_source_id = ANY(:meme_source_ids)
              AND reaction.reaction_id IS NOT NULL
            GROUP BY reaction.user_id, meme.meme_source_id
            ON CONFLICT (user_id, meme_source_id) DO UPDATE SET
                nlikes = EXCLUDED.nlikes,
                ndislikes = EXCLUDED.ndislikes,
                updated_at = EXCLUDED.updated_at
            """
        ),
        params,
    )


async def calculate_user_meme_source_stats() -> None:
    """Recompute per-user per-source stats for the scheduled batch.

    Normally the scheduled batch is the sole writer to user_meme_source_stats,
    but Prefect retries can cause concurrent runs. Use the deduplication lock so its full-batch
    snapshot cannot overwrite a targeted duplicate-merge refresh.
    """
    query = """
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
            AND R.user_id IN (
                SELECT DISTINCT user_id
                FROM user_meme_reaction
                WHERE reacted_at > NOW() - INTERVAL '7 days'
            )
        GROUP BY 1,2
        ORDER BY 1,2
        ON CONFLICT (user_id, meme_source_id) DO
        UPDATE SET
            nlikes = EXCLUDED.nlikes,
            ndislikes = EXCLUDED.ndislikes,
            updated_at = EXCLUDED.updated_at
    """

    async def _calculate(conn: AsyncConnection) -> None:
        await conn.execute(text("SELECT pg_advisory_xact_lock(1179012429, 1)"))
        await conn.execute(text(query))

    await run_in_transaction(_calculate)
