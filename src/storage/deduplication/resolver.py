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
                meme_id, nlikes, ndislikes, nmemes_sent, age_days, sec_to_react, updated_at
            )
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
            FROM meme M
            LEFT JOIN user_meme_reaction R
                ON R.meme_id = M.id
            WHERE M.id = :original_id
            GROUP BY M.id
            ON CONFLICT (meme_id) DO UPDATE SET
                nlikes = EXCLUDED.nlikes,
                ndislikes = EXCLUDED.ndislikes,
                nmemes_sent = EXCLUDED.nmemes_sent,
                age_days = EXCLUDED.age_days,
                sec_to_react = EXCLUDED.sec_to_react,
                updated_at = EXCLUDED.updated_at
        """
        ),
        {"original_id": original_id},
    )
