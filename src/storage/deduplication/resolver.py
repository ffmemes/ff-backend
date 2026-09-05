from collections.abc import Collection
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from src.database import run_in_transaction
from src.stats.meme import calculate_meme_reactions_and_engagement_on_connection
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
            text("SELECT id, duplicate_of FROM meme WHERE id = :meme_id FOR UPDATE"),
            {"meme_id": current_id},
        )
        if not row or row["duplicate_of"] is None:
            return current_id

        current_id = row["duplicate_of"]
        if current_id in seen:
            raise ValueError("Existing cycle in meme duplicate links")
        seen.add(current_id)


async def resolve_duplicate(
    dupe_id: int,
    original_id: int,
    *,
    reason: str,
) -> DuplicateResolution:
    """Mark a meme as duplicate and move all safe reaction history to the original."""
    resolution = await _resolve_duplicate(
        dupe_id,
        original_id,
        reason=reason,
        allowed_dupe_statuses=None,
    )
    assert resolution is not None
    return resolution


async def resolve_duplicate_if_current_status(
    dupe_id: int,
    original_id: int,
    *,
    reason: str,
    allowed_dupe_statuses: Collection[str],
    prefer_canonical: bool = False,
) -> DuplicateResolution | None:
    """Resolve only if the dupe still has one of the expected current statuses."""
    return await _resolve_duplicate(
        dupe_id,
        original_id,
        reason=reason,
        allowed_dupe_statuses=allowed_dupe_statuses,
        prefer_canonical=prefer_canonical,
    )


async def _resolve_duplicate(
    dupe_id: int,
    original_id: int,
    *,
    reason: str,
    allowed_dupe_statuses: Collection[str] | None,
    prefer_canonical: bool = False,
) -> DuplicateResolution | None:
    """Mark a meme as duplicate and move all safe reaction history to the original."""

    async def _resolve(conn: AsyncConnection) -> DuplicateResolution | None:
        # Dedup runs infrequently. One transaction lock also covers file-id and
        # upload merges, preventing two workers from creating opposite links.
        await conn.execute(text("SELECT pg_advisory_xact_lock(1179012429, 1)"))
        current = await _fetch_one(
            conn,
            text("SELECT id, status FROM meme WHERE id = :meme_id FOR UPDATE"),
            {"meme_id": dupe_id},
        )
        if allowed_dupe_statuses is not None and (
            not current or current["status"] not in allowed_dupe_statuses
        ):
            return None

        canonical_original_id = await _canonical_original_id(conn, original_id)
        if dupe_id == canonical_original_id:
            # A stale candidate may already have been merged into this meme.
            # Never turn an original into its own duplicate or move/delete its history.
            if allowed_dupe_statuses is not None:
                return None
            return DuplicateResolution(dupe_id, canonical_original_id, reason, 0, 0, 0, 0)

        resolved_dupe_id = dupe_id
        if prefer_canonical:
            original = await _fetch_one(
                conn,
                text("SELECT id, status FROM meme WHERE id = :meme_id FOR UPDATE"),
                {"meme_id": canonical_original_id},
            )
            if not original or original["status"] not in {"ok", "published"}:
                return None
            # Two approved copies: preserve published identity, otherwise the
            # oldest ID. Unreviewed uploads keep their existing directional policy.
            if (current["status"] != "published", dupe_id) < (
                original["status"] != "published",
                canonical_original_id,
            ):
                resolved_dupe_id, canonical_original_id = canonical_original_id, dupe_id

        if not await _mark_duplicate(
            conn,
            resolved_dupe_id,
            canonical_original_id,
            allowed_dupe_statuses=allowed_dupe_statuses,
        ):
            return None

        reactions_moved = await _move_user_reactions(conn, resolved_dupe_id, canonical_original_id)
        chat_reactions_moved = await _move_chat_reactions(
            conn, resolved_dupe_id, canonical_original_id
        )
        reactions_dropped = await _delete_user_reactions(conn, resolved_dupe_id)
        chat_reactions_dropped = await _delete_chat_reactions(conn, resolved_dupe_id)

        await conn.execute(
            text("DELETE FROM meme_stats WHERE meme_id = :dupe_id"),
            {"dupe_id": resolved_dupe_id},
        )
        await conn.execute(
            text(
                """
                UPDATE meme
                SET duplicate_of = :original_id
                WHERE duplicate_of = :dupe_id
            """
            ),
            {"dupe_id": resolved_dupe_id, "original_id": canonical_original_id},
        )
        await _refresh_original_stats(conn, canonical_original_id)

        return DuplicateResolution(
            dupe_id=resolved_dupe_id,
            original_id=canonical_original_id,
            reason=reason,
            reactions_moved=reactions_moved,
            reactions_dropped=reactions_dropped,
            chat_reactions_moved=chat_reactions_moved,
            chat_reactions_dropped=chat_reactions_dropped,
        )

    return await run_in_transaction(_resolve)


async def _mark_duplicate(
    conn: AsyncConnection,
    dupe_id: int,
    original_id: int,
    *,
    allowed_dupe_statuses: Collection[str] | None,
) -> bool:
    params: dict[str, Any] = {"dupe_id": dupe_id, "original_id": original_id}
    status_filter = ""
    if allowed_dupe_statuses is not None:
        params["allowed_dupe_statuses"] = list(allowed_dupe_statuses)
        status_filter = "AND status = ANY(:allowed_dupe_statuses)"

    row = await _fetch_one(
        conn,
        text(
            f"""
            UPDATE meme
            SET status = 'duplicate', duplicate_of = :original_id
            WHERE id = :dupe_id
              {status_filter}
            RETURNING id
        """
        ),
        params,
    )
    return allowed_dupe_statuses is None or row is not None


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
    await calculate_meme_reactions_and_engagement_on_connection(
        conn,
        meme_ids=[original_id],
        include_user_history=True,
    )
