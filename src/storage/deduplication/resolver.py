from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from src.database import run_in_transaction
from src.storage.deduplication.models import DuplicateResolution


async def _fetch_one(
    conn: AsyncConnection,
    query,
    params: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    result = await conn.execute(query, params or {})
    row = result.first()
    return row._asdict() if row is not None else None


async def _count(
    conn: AsyncConnection,
    query,
    params: dict[str, Any],
    field: str,
) -> int:
    row = await _fetch_one(conn, query, params)
    return int(row[field]) if row else 0


async def _canonical_original_id(conn: AsyncConnection, meme_id: int) -> int:
    """Follow duplicate_of links so new duplicates point at a real original."""
    current_id = meme_id
    seen = {meme_id}

    while True:
        row = await _fetch_one(
            conn,
            text("SELECT id, duplicate_of FROM meme WHERE id = :meme_id"),
            {"meme_id": current_id},
        )
        if not row or row["duplicate_of"] is None:
            return current_id

        current_id = row["duplicate_of"]
        if current_id in seen:
            return current_id
        seen.add(current_id)


async def resolve_duplicate(
    dupe_id: int,
    original_id: int,
    *,
    reason: str,
) -> DuplicateResolution:
    """Mark a meme as duplicate and move all safe reaction history to the original."""

    async def _resolve(conn: AsyncConnection) -> DuplicateResolution:
        canonical_original_id = await _canonical_original_id(conn, original_id)

        reactions_moved = await _move_user_reactions(conn, dupe_id, canonical_original_id)
        chat_reactions_moved = await _move_chat_reactions(conn, dupe_id, canonical_original_id)
        reactions_dropped = await _delete_user_reactions(conn, dupe_id)
        chat_reactions_dropped = await _delete_chat_reactions(conn, dupe_id)

        await conn.execute(
            text("DELETE FROM meme_stats WHERE meme_id = :dupe_id"),
            {"dupe_id": dupe_id},
        )
        await conn.execute(
            text(
                """
                UPDATE meme
                SET status = 'duplicate', duplicate_of = :original_id
                WHERE id = :dupe_id
            """
            ),
            {"dupe_id": dupe_id, "original_id": canonical_original_id},
        )
        await conn.execute(
            text(
                """
                UPDATE meme
                SET duplicate_of = :original_id
                WHERE duplicate_of = :dupe_id
            """
            ),
            {"dupe_id": dupe_id, "original_id": canonical_original_id},
        )
        await _refresh_original_stats(conn, canonical_original_id)

        return DuplicateResolution(
            dupe_id=dupe_id,
            original_id=canonical_original_id,
            reason=reason,
            reactions_moved=reactions_moved,
            reactions_dropped=reactions_dropped,
            chat_reactions_moved=chat_reactions_moved,
            chat_reactions_dropped=chat_reactions_dropped,
        )

    return await run_in_transaction(_resolve)


async def _move_user_reactions(
    conn: AsyncConnection,
    dupe_id: int,
    original_id: int,
) -> int:
    return await _count(
        conn,
        text(
            """
            WITH moved AS (
                INSERT INTO user_meme_reaction
                    (user_id, meme_id, recommended_by, sent_at, reaction_id, reacted_at)
                SELECT user_id, :original_id, recommended_by, sent_at, reaction_id, reacted_at
                FROM user_meme_reaction source
                WHERE source.meme_id = :dupe_id
                  AND NOT EXISTS (
                      SELECT 1 FROM user_meme_reaction existing
                      WHERE existing.user_id = source.user_id
                        AND existing.meme_id = :original_id
                  )
                ON CONFLICT (user_id, meme_id) DO NOTHING
                RETURNING 1
            )
            SELECT count(*) AS moved FROM moved
        """
        ),
        {"dupe_id": dupe_id, "original_id": original_id},
        "moved",
    )


async def _move_chat_reactions(
    conn: AsyncConnection,
    dupe_id: int,
    original_id: int,
) -> int:
    return await _count(
        conn,
        text(
            """
            WITH moved AS (
                INSERT INTO chat_meme_reaction
                    (chat_id, meme_id, user_id, reaction, reacted_at)
                SELECT chat_id, :original_id, user_id, reaction, reacted_at
                FROM chat_meme_reaction source
                WHERE source.meme_id = :dupe_id
                  AND NOT EXISTS (
                      SELECT 1 FROM chat_meme_reaction existing
                      WHERE existing.chat_id = source.chat_id
                        AND existing.user_id = source.user_id
                        AND existing.meme_id = :original_id
                  )
                ON CONFLICT (chat_id, meme_id, user_id) DO NOTHING
                RETURNING 1
            )
            SELECT count(*) AS moved FROM moved
        """
        ),
        {"dupe_id": dupe_id, "original_id": original_id},
        "moved",
    )


async def _delete_user_reactions(conn: AsyncConnection, dupe_id: int) -> int:
    return await _count(
        conn,
        text(
            """
            WITH deleted AS (
                DELETE FROM user_meme_reaction WHERE meme_id = :dupe_id RETURNING 1
            )
            SELECT count(*) AS deleted FROM deleted
        """
        ),
        {"dupe_id": dupe_id},
        "deleted",
    )


async def _delete_chat_reactions(conn: AsyncConnection, dupe_id: int) -> int:
    return await _count(
        conn,
        text(
            """
            WITH deleted AS (
                DELETE FROM chat_meme_reaction WHERE meme_id = :dupe_id RETURNING 1
            )
            SELECT count(*) AS deleted FROM deleted
        """
        ),
        {"dupe_id": dupe_id},
        "deleted",
    )


async def refresh_original_stats(original_id: int) -> None:
    async def _refresh(conn: AsyncConnection) -> None:
        await _refresh_original_stats(conn, original_id)

    await run_in_transaction(_refresh)


async def _refresh_original_stats(conn: AsyncConnection, original_id: int) -> None:
    await conn.execute(
        text(
            """
            INSERT INTO meme_stats (
                meme_id, nlikes, ndislikes, nmemes_sent,
                age_days, sec_to_react, updated_at,
                lr_smoothed, engagement_score
            )
            WITH AFFECTED_MEME AS (
                SELECT id, published_at
                FROM meme
                WHERE id = :original_id
            ),
            AFFECTED_USERS AS (
                SELECT DISTINCT user_id
                FROM user_meme_reaction
                WHERE meme_id = :original_id
            ),
            BASE_REACTIONS AS (
                SELECT
                    R.user_id, R.meme_id, R.reaction_id,
                    R.sent_at, R.reacted_at,
                    CASE WHEN R.reaction_id = 1 THEN 1
                         WHEN R.reaction_id IS NOT NULL THEN -1
                    END AS like_sym,
                    EXTRACT(EPOCH FROM R.reacted_at - R.sent_at) AS sec_to_react,
                    MAX(CASE WHEN R.reaction_id IS NOT NULL THEN R.sent_at END)
                        OVER (PARTITION BY R.user_id) AS user_last_reaction_sent_at
                FROM user_meme_reaction R
                WHERE R.user_id IN (SELECT user_id FROM AFFECTED_USERS)
            ),
            WITH_USER_AVGS AS (
                SELECT *,
                    AVG(like_sym) OVER (
                        PARTITION BY user_id ORDER BY sent_at
                    ) AS lr_avg,
                    COUNT(like_sym) OVER (
                        PARTITION BY user_id ORDER BY sent_at
                    ) AS n_user_lr_reactions,
                    CASE
                        WHEN reaction_id = 1 THEN 1.0
                        WHEN reaction_id = 2
                            AND sec_to_react BETWEEN 0.5 AND 60
                            AND sec_to_react > 3 THEN -1.0
                        WHEN reaction_id = 2
                            AND sec_to_react BETWEEN 0.5 AND 60
                            AND sec_to_react <= 3 THEN -0.5
                        WHEN reaction_id = 2 THEN -1.0
                        WHEN reaction_id IS NULL
                            AND sent_at < user_last_reaction_sent_at THEN -0.3
                        ELSE NULL
                    END AS engagement_value
                FROM BASE_REACTIONS
            ),
            SMOOTHED AS (
                SELECT
                    user_id, meme_id,
                    CASE WHEN n_user_lr_reactions >= 10
                        THEN like_sym - lr_avg
                        ELSE NULL
                    END AS lr_smoothed_val,
                    CASE WHEN engagement_value IS NOT NULL THEN
                        engagement_value - AVG(engagement_value) OVER (
                            PARTITION BY user_id ORDER BY sent_at
                        )
                        ELSE NULL
                    END AS es_smoothed_val
                FROM WITH_USER_AVGS
            ),
            MEME_SCORES AS (
                SELECT
                    meme_id,
                    AVG(lr_smoothed_val) AS lr_smoothed,
                    AVG(es_smoothed_val) AS engagement_score,
                    COUNT(lr_smoothed_val) AS n_lr_reactions,
                    COUNT(es_smoothed_val) AS n_es_reactions
                FROM SMOOTHED
                WHERE meme_id = :original_id
                GROUP BY meme_id
            ),
            BASIC_COUNTS AS (
                SELECT
                    M.id AS meme_id,
                    COUNT(R.*) FILTER (WHERE R.reaction_id = 1) AS nlikes,
                    COUNT(R.*) FILTER (WHERE R.reaction_id = 2) AS ndislikes,
                    COUNT(R.*) AS nmemes_sent,
                    EXTRACT('DAYS' FROM NOW() - M.published_at)::int AS age_days,
                    COALESCE(EXTRACT(
                        EPOCH FROM percentile_cont(0.5)
                            WITHIN GROUP (ORDER BY R.reacted_at - R.sent_at)
                            FILTER (
                                WHERE R.reacted_at - R.sent_at
                                BETWEEN '0.5 second'
                                AND '1 minute'
                            )
                    ), 99999) AS sec_to_react,
                    NOW() AS updated_at
                FROM AFFECTED_MEME M
                LEFT JOIN user_meme_reaction R
                    ON R.meme_id = M.id
                GROUP BY M.id, M.published_at
            )
            SELECT
                BC.meme_id, BC.nlikes, BC.ndislikes, BC.nmemes_sent,
                BC.age_days, BC.sec_to_react, BC.updated_at,
                COALESCE(
                    CASE WHEN MS.n_lr_reactions >= 3
                        THEN MS.lr_smoothed ELSE NULL END,
                    0
                ) AS lr_smoothed,
                COALESCE(
                    CASE WHEN MS.n_es_reactions >= 3
                        THEN MS.engagement_score ELSE NULL END,
                    0
                ) AS engagement_score
            FROM BASIC_COUNTS BC
            LEFT JOIN MEME_SCORES MS ON MS.meme_id = BC.meme_id
            ON CONFLICT (meme_id) DO UPDATE SET
                nlikes = EXCLUDED.nlikes,
                ndislikes = EXCLUDED.ndislikes,
                nmemes_sent = EXCLUDED.nmemes_sent,
                age_days = EXCLUDED.age_days,
                sec_to_react = EXCLUDED.sec_to_react,
                updated_at = EXCLUDED.updated_at,
                lr_smoothed = EXCLUDED.lr_smoothed,
                engagement_score = EXCLUDED.engagement_score
        """
        ),
        {"original_id": original_id},
    )
