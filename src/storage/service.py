from typing import Any

from sqlalchemy import bindparam, nulls_first, or_, select, text

from src.database import (
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


async def get_telegram_sources_to_parse(limit=10) -> list[dict[str, Any]]:
    select_query = (
        select(meme_source)
        .where(meme_source.c.type == MemeSourceType.TELEGRAM)
        .where(meme_source.c.status == MemeSourceStatus.PARSING_ENABLED)
        .order_by(nulls_first(meme_source.c.parsed_at))
        .limit(limit)
    )
    return await fetch_all(select_query)


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
    update_query = (
        meme.update().where(meme.c.id == meme_id).values(**kwargs).returning(meme)
    )
    return await fetch_one(update_query)


async def get_pending_memes() -> list[dict[str, Any]]:
    select_query = (
        select(meme)
        .where(meme.c.status == MemeStatus.CREATED)
        .where(meme.c.telegram_file_id.is_not(None))
        .where(
            or_(
                meme.c.ocr_result.is_not(None),
                meme.c.type != MemeType.IMAGE,
            )
        )
        .order_by(nulls_first(meme.c.created_at))
    )
    return await fetch_all(select_query)


async def get_memes_to_ocr(limit=100):
    select_query = """
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
        LEFT JOIN meme_raw_vk MRV
            ON MRV.id = M.raw_meme_id AND MS.type = 'vk'
        LEFT JOIN meme_raw_telegram MRT
            ON MRT.id = M.raw_meme_id AND MS.type = 'telegram'
        LEFT JOIN meme_raw_ig MRI
            ON MRI.id = M.raw_meme_id AND MS.type = 'instagram'
        WHERE 1=1
            AND M.ocr_result IS NULL
            AND M.status != 'broken_content_link'
            AND M.type = 'image'
        ORDER BY M.created_at
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
        LIMIT {limit}
    """

    return await fetch_all(text(select_query))


async def update_meme_status_of_ready_memes() -> list[dict[str, Any]]:
    """Changes the status of memes to 'ok' if they are ready to be published."""
    update_query = (
        meme.update()
        .where(meme.c.status == MemeStatus.CREATED)
        .where(meme.c.telegram_file_id.is_not(None))
        .where(
            or_(
                meme.c.ocr_result.is_not(None),
                meme.c.type != MemeType.IMAGE,
            )
        )
        .where(meme.c.duplicate_of.is_(None))
        .values(status=MemeStatus.OK)
        .returning(meme)
    )
    return await fetch_all(update_query)


async def find_meme_duplicate(meme_id: int, imagetext: str) -> int | None:
    if len(imagetext) <= 11:  # skip all memes with less than 11 letters
        return None

    select_query = """
        SELECT
            M.id
        FROM meme M
        WHERE M.id < :meme_id
            AND ocr_result IS NOT NULL
            AND similarity(
                :imagetext,
                M.ocr_result ->> 'text'
              ) >= 0.6
            AND M.status = 'ok'
        ORDER BY M.id ASC
        LIMIT 1
    """
    select_query = text(select_query).bindparams(
        bindparam("meme_id", value=meme_id), bindparam("imagetext", value=imagetext)
    )

    res = await fetch_one(select_query)
    if res:
        return res["id"]
    return None
