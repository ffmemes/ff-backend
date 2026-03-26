from typing import Any

from sqlalchemy import nulls_first, select, text

from src.database import (
    execute,
    fetch_all,
    fetch_one,
    meme,
    meme_source,
)
from src.storage.constants import (
    MemeSourceStatus,
    MemeSourceType,
    MemeStatus,
    MemeType,
)


async def get_telegram_sources_to_parse(limit=25) -> list[dict[str, Any]]:
    # Quality-weighted selection: best sources parse first.
    # Sources with no stats get neutral score (0.5) so they still parse.
    # NULLS FIRST on parsed_at ensures never-parsed sources get priority.
    query = f"""
        SELECT ms.*
        FROM meme_source ms
        LEFT JOIN meme_source_stats mss ON mss.meme_source_id = ms.id
        WHERE ms.type = '{MemeSourceType.TELEGRAM.value}'
          AND ms.status = '{MemeSourceStatus.PARSING_ENABLED.value}'
        ORDER BY
            ms.parsed_at IS NOT NULL,
            ms.parsed_at ASC,
            COALESCE(
                mss.nlikes::float / NULLIF(mss.nlikes + mss.ndislikes, 0), 0.5
            ) * LN(COALESCE(mss.nmemes_sent, 0) + 2) DESC
        LIMIT {int(limit)}
    """
    return await fetch_all(text(query))


async def get_vk_sources_to_parse(limit=10) -> list[dict[str, Any]]:
    select_query = (
        select(meme_source)
        .where(meme_source.c.type == MemeSourceType.VK)
        .where(meme_source.c.status == MemeSourceStatus.PARSING_ENABLED)
        .order_by(nulls_first(meme_source.c.parsed_at))
        .limit(limit)
    )
    return await fetch_all(select_query)


async def get_ig_sources_to_parse(limit=10) -> list[dict[str, Any]]:
    select_query = (
        select(meme_source)
        .where(meme_source.c.type == MemeSourceType.INSTAGRAM)
        .where(meme_source.c.status == MemeSourceStatus.PARSING_ENABLED)
        .order_by(nulls_first(meme_source.c.parsed_at))
        .limit(limit)
    )
    return await fetch_all(select_query)


async def update_meme_source(meme_source_id: int, **kwargs) -> dict[str, Any] | None:
    update_query = (
        meme_source.update()
        .where(meme_source.c.id == meme_source_id)
        .values(**kwargs)
        .returning(meme_source)
    )
    return await fetch_one(update_query)


async def update_meme(meme_id: int, **kwargs) -> dict[str, Any] | None:
    update_query = meme.update().where(meme.c.id == meme_id).values(**kwargs).returning(meme)
    return await fetch_one(update_query)


async def get_pending_memes(limit: int = 500) -> list[dict[str, Any]]:
    select_query = (
        select(meme)
        .where(meme.c.status == MemeStatus.CREATED)
        .where(meme.c.telegram_file_id.is_not(None))
        .order_by(meme.c.created_at.desc())
        .limit(limit)
    )
    return await fetch_all(select_query)


async def get_memes_to_ocr(limit=100):
    select_query = f"""
        SELECT
            M.*,
            MS.type meme_source_type,
            COALESCE(
                MRV.media->>0,
                MRT.media->0->>'url',
                MRI.media->0->>'url'
            ) content_url
        FROM meme M
        INNER JOIN meme_source MS
            ON MS.id = M.meme_source_id
        LEFT JOIN meme_source_stats MSS
            ON MSS.meme_source_id = MS.id
        LEFT JOIN meme_raw_vk MRV
            ON MRV.id = M.raw_meme_id AND MS.type = 'vk'
            AND MRV.reposts / (MRV.likes + 1.) > 0.02
        LEFT JOIN meme_raw_telegram MRT
            ON MRT.id = M.raw_meme_id AND MS.type = 'telegram'
            AND MRT.views > 200
        LEFT JOIN meme_raw_ig MRI
            ON MRI.id = M.raw_meme_id AND MS.type = 'instagram'
            AND MRI.comments / (MRI.likes + 1.) > 0.01
        WHERE 1=1
            AND M.ocr_result IS NULL
            AND M.language_code IN ('en', 'ru')
            AND M.status != 'broken_content_link'
            AND M.type = 'image'
            AND COALESCE(
                MRV.media->>0,
                MRT.media->0->>'url',
                MRI.media->0->>'url'
            ) IS NOT NULL
        ORDER BY
            DATE(M.created_at) DESC,
            (MSS.nlikes + 0.001) / (MSS.ndislikes + 0.001) DESC
        LIMIT {limit}
    """
    return await fetch_all(text(select_query))


async def get_unloaded_tg_memes(limit) -> list[dict[str, Any]]:
    """Returns memes from Telegram, that have not been yet uploaded to Telegram."""

    select_query = f"""
        SELECT
            meme.id,
            meme.type,
            MRT.media->0->>'url' content_url
        FROM meme
        INNER JOIN meme_source
            ON meme_source.id = meme.meme_source_id
            AND meme_source.type = 'telegram'
        INNER JOIN meme_raw_telegram MRT
            ON MRT.id = meme.raw_meme_id
            AND MRT.meme_source_id = meme.meme_source_id
        WHERE 1=1
            AND (
                meme.telegram_file_id IS NULL
                OR meme.status = 'broken_content_link'
            )
            AND MRT.media->0->>'url' IS NOT NULL
            AND COALESCE(MRT.updated_at, MRT.created_at) >= NOW() - INTERVAL '24 hours'
        ORDER BY meme.published_at DESC
        LIMIT {limit}
    """
    return await fetch_all(text(select_query))


async def get_unloaded_vk_memes(limit: int) -> list[dict[str, Any]]:
    """Returns memes from VK, that have not been yet uploaded to Telegram."""

    select_query = f"""
        SELECT
            meme.id,
            meme.type,
            meme_raw_vk.media->>0 content_url
        FROM meme
        INNER JOIN meme_source
            ON meme_source.id = meme.meme_source_id
            AND meme_source.type = '{MemeSourceType.VK.value}'
        INNER JOIN meme_raw_vk
            ON meme_raw_vk.id = meme.raw_meme_id
            AND meme_raw_vk.meme_source_id = meme.meme_source_id
        WHERE 1=1
            AND meme.telegram_file_id IS NULL
        ORDER BY meme.published_at DESC
        LIMIT {limit}
    """
    return await fetch_all(text(select_query))


async def get_unloaded_ig_memes(limit: int) -> list[dict[str, Any]]:
    select_query = f"""
        SELECT
            meme.id,
            meme.type,
            media->0->>'url' content_url
        FROM meme
        INNER JOIN meme_source
            ON meme_source.id = meme.meme_source_id
            AND meme_source.type = '{MemeSourceType.INSTAGRAM.value}'
        INNER JOIN meme_raw_ig MRI
            ON MRI.id = meme.raw_meme_id
            AND MRI.meme_source_id = meme.meme_source_id
        WHERE 1=1
            AND meme.telegram_file_id IS NULL
        ORDER BY meme.published_at DESC
        LIMIT {limit}
    """

    return await fetch_all(text(select_query))


async def update_meme_status_of_ready_memes() -> list[dict[str, Any]]:
    """Changes the status of memes to 'ok' if they are ready to be published."""
    update_query = (
        meme.update()
        .where(meme.c.status == MemeStatus.CREATED)
        .where(meme.c.telegram_file_id.is_not(None))
        .where(meme.c.duplicate_of.is_(None))
        .values(status=MemeStatus.OK)
        .returning(meme)
    )
    return await fetch_all(update_query)


async def find_meme_duplicate_by_file_id(
    meme_id: int, telegram_file_id: str
) -> int | None:
    """Find an existing meme with the same telegram_file_id."""
    query = text("""
        SELECT id FROM meme
        WHERE telegram_file_id = :file_id
          AND status IN ('ok', 'created')
          AND id < :meme_id
        ORDER BY id ASC
        LIMIT 1
    """)
    res = await fetch_one(query, {"file_id": telegram_file_id, "meme_id": meme_id})
    if res:
        return res["id"]
    return None


async def find_meme_duplicate(meme_id: int, imagetext: str) -> int | None:
    if len(imagetext) <= 11:  # skip all memes with less than 11 letters
        return None

    select_query = text("""
        SELECT
            M.id
        FROM meme M
        WHERE M.id < :meme_id
            AND M.status = 'ok'
            AND M.type = 'image'
            AND M.ocr_result IS NOT NULL
            AND (M.ocr_result ->> 'text') % :imagetext
        ORDER BY M.id ASC
        LIMIT 1
    """).bindparams(meme_id=meme_id, imagetext=imagetext)

    res = await fetch_one(select_query)
    if res:
        return res["id"]
    return None


async def resolve_meme_duplicate(dupe_id: int, original_id: int) -> dict[str, int]:
    """Mark a meme as duplicate with full cleanup.

    1. Move reactions from dupe → original (skip conflicts)
    2. Delete remaining reactions on dupe
    3. Delete meme_stats for dupe
    4. Set meme status='duplicate', duplicate_of=original_id

    Stats for original will auto-recalculate on next 5-15 min cycle.
    Returns counts: {moved, conflicts, deleted_stats}.
    """
    # 1. Move non-conflicting reactions to original
    move_query = text("""
        WITH moved AS (
            INSERT INTO user_meme_reaction
                (user_id, meme_id, recommended_by, sent_at, reaction_id, reacted_at)
            SELECT user_id, :original_id, recommended_by, sent_at, reaction_id, reacted_at
            FROM user_meme_reaction
            WHERE meme_id = :dupe_id
              AND NOT EXISTS (
                  SELECT 1 FROM user_meme_reaction existing
                  WHERE existing.user_id = user_meme_reaction.user_id
                    AND existing.meme_id = :original_id
              )
            ON CONFLICT (user_id, meme_id) DO NOTHING
            RETURNING 1
        )
        SELECT count(*) AS moved FROM moved
    """)
    res = await fetch_one(move_query, {"dupe_id": dupe_id, "original_id": original_id})
    moved = res["moved"] if res else 0

    # 2. Delete all reactions remaining on dupe (conflicts + already moved)
    delete_reactions = text("""
        WITH deleted AS (
            DELETE FROM user_meme_reaction WHERE meme_id = :dupe_id RETURNING 1
        )
        SELECT count(*) AS conflicts FROM deleted
    """)
    res = await fetch_one(delete_reactions, {"dupe_id": dupe_id})
    conflicts = res["conflicts"] if res else 0

    # 3. Delete meme_stats for dupe (stale, will not regenerate since no reactions)
    await execute(
        text("DELETE FROM meme_stats WHERE meme_id = :dupe_id"),
        {"dupe_id": dupe_id},
    )

    # 4. Mark meme as duplicate
    await execute(
        text("""
            UPDATE meme
            SET status = 'duplicate', duplicate_of = :original_id
            WHERE id = :dupe_id
        """),
        {"dupe_id": dupe_id, "original_id": original_id},
    )

    return {"moved": moved, "conflicts": conflicts}


async def resolve_all_file_id_duplicates() -> dict[str, int]:
    """Find and resolve all memes with duplicate telegram_file_id.

    For each group of memes sharing a file_id with status='ok':
    keeps the oldest (smallest id), resolves the rest as duplicates.
    Returns total counts.
    """
    # Find all file_id duplicate groups
    dupes_query = text("""
        SELECT id, telegram_file_id,
            FIRST_VALUE(id) OVER (
                PARTITION BY telegram_file_id ORDER BY id ASC
            ) AS original_id
        FROM meme
        WHERE status = 'ok'
          AND telegram_file_id IS NOT NULL
          AND telegram_file_id IN (
              SELECT telegram_file_id FROM meme
              WHERE status = 'ok' AND telegram_file_id IS NOT NULL
              GROUP BY telegram_file_id HAVING count(*) > 1
          )
    """)
    rows = await fetch_all(dupes_query)

    total_moved = 0
    total_conflicts = 0
    total_resolved = 0

    for row in rows:
        if row["id"] == row["original_id"]:
            continue  # skip the keeper
        result = await resolve_meme_duplicate(row["id"], row["original_id"])
        total_moved += result["moved"]
        total_conflicts += result["conflicts"]
        total_resolved += 1

    return {
        "resolved": total_resolved,
        "reactions_moved": total_moved,
        "reactions_dropped": total_conflicts,
    }
