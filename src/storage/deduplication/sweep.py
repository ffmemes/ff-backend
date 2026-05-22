from sqlalchemy import text

from src.database import fetch_all
from src.storage.deduplication.resolver import resolve_duplicate


async def sweep_file_id_duplicates() -> dict[str, int]:
    """Resolve any exact Telegram file_id duplicates that slipped past batch processing."""
    rows = await fetch_all(
        text(
            """
            WITH duplicate_groups AS (
                SELECT telegram_file_id
                FROM meme
                WHERE status IN ('ok', 'published')
                  AND telegram_file_id IS NOT NULL
                GROUP BY telegram_file_id
                HAVING count(*) > 1
            ),
            canonical AS (
                SELECT DISTINCT ON (m.telegram_file_id)
                    m.telegram_file_id,
                    m.id AS original_id
                FROM meme m
                INNER JOIN duplicate_groups g
                    ON g.telegram_file_id = m.telegram_file_id
                WHERE m.status IN ('ok', 'published')
                ORDER BY
                    m.telegram_file_id,
                    CASE WHEN m.status = 'published' THEN 0 ELSE 1 END,
                    m.id ASC
            )
            SELECT m.id, m.telegram_file_id, canonical.original_id
            FROM meme m
            INNER JOIN canonical
                ON canonical.telegram_file_id = m.telegram_file_id
            WHERE m.status = 'ok'
              AND m.id != canonical.original_id
        """
        )
    )

    total_moved = 0
    total_dropped = 0
    total_resolved = 0

    for row in rows:
        if row["id"] == row["original_id"]:
            continue
        result = await resolve_duplicate(
            row["id"],
            row["original_id"],
            reason="telegram_file_id_sweep",
        )
        total_moved += result.reactions_moved
        total_dropped += result.reactions_dropped
        total_resolved += 1

    return {
        "resolved": total_resolved,
        "reactions_moved": total_moved,
        "reactions_dropped": total_dropped,
    }
