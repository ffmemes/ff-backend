from datetime import datetime
from typing import Any

from sqlalchemy import bindparam, nulls_first, or_, select, text
from sqlalchemy.dialects.postgresql import insert

from src.database import (
    execute,
    fetch_all,
    fetch_one,
    meme,
    meme_raw_telegram,
    meme_raw_vk,
    meme_source,
)
from src.storage.constants import (
    MEME_RAW_TELEGRAM_MEME_SOURCE_POST_UNIQUE_CONSTRAINT,
    MEME_RAW_VK_MEME_SOURCE_POST_UNIQUE_CONSTRAINT,
    MemeSourceStatus,
    MemeSourceType,
    MemeStatus,
    MemeType,
)
from src.storage.parsers.schemas import (
    TgChannelPostParsingResult,
    VkGroupPostParsingResult,
)


async def insert_parsed_posts_from_telegram(
    meme_source_id: int,
    telegram_posts: list[TgChannelPostParsingResult],
) -> None:
    posts = [
        post.model_dump() | {"meme_source_id": meme_source_id}
        for post in telegram_posts
    ]
    insert_statement = insert(meme_raw_telegram).values(posts)
    insert_posts_query = insert_statement.on_conflict_do_update(
        constraint=MEME_RAW_TELEGRAM_MEME_SOURCE_POST_UNIQUE_CONSTRAINT,
        set_={
            "media": insert_statement.excluded.media,
            "views": insert_statement.excluded.views,
            "updated_at": datetime.utcnow(),
        },
    )

    await execute(insert_posts_query)


async def insert_parsed_posts_from_vk(
    meme_source_id: int,
    vk_posts: list[VkGroupPostParsingResult],
) -> None:
    posts = [
        post.model_dump() | {"meme_source_id": meme_source_id} for post in vk_posts
    ]
    insert_statement = insert(meme_raw_vk).values(posts)
    insert_posts_query = insert_statement.on_conflict_do_update(
        constraint=MEME_RAW_VK_MEME_SOURCE_POST_UNIQUE_CONSTRAINT,
        set_={
            "media": insert_statement.excluded.media,
            "views": insert_statement.excluded.views,
            "likes": insert_statement.excluded.likes,
            "reposts": insert_statement.excluded.reposts,
            "comments": insert_statement.excluded.comments,
            "updated_at": datetime.utcnow(),
        },
    )

    await execute(insert_posts_query)


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


async def update_meme_source(meme_source_id: int, **kwargs) -> dict[str, Any] | None:
    update_query = (
        meme_source.update()
        .where(meme_source.c.id == meme_source_id)
        .values(**kwargs)
        .returning(meme_source)
    )
    return await fetch_one(update_query)


# TODO: separate file for ETL scripts?
async def etl_memes_from_raw_telegram_posts() -> None:
    insert_query = """
        INSERT INTO meme (
            meme_source_id,
            raw_meme_id,
            caption,
            status,
            type,
            language_code,
            published_at
        )
        SELECT
            DISTINCT ON (COALESCE(MRT.forwarded_url, random()::text))
            MRT.meme_source_id,
            MRT.id AS raw_meme_id,
            MRT.content AS caption,
            'created' AS status,
            CASE
                WHEN media->0->>'duration' IS NOT NULL THEN 'video'
                ELSE 'image'
            END AS type,
            MS.language_code AS language_code,
            MRT.date AS published_at
        FROM meme_raw_telegram MRT
        INNER JOIN meme_source MS
            ON MS.id = MRT.meme_source_id
        WHERE 1=1
            AND JSONB_ARRAY_LENGTH(MRT.media) = 1
            AND COALESCE(MRT.updated_at, MRT.created_at) >= NOW() - INTERVAL '24 hours'
        ON CONFLICT (meme_source_id, raw_meme_id)
        DO UPDATE
        SET
            status = CASE
                WHEN meme.status != 'broken_content_link'
                THEN meme.status
                ELSE 'created'
            END
    """
    await execute(text(insert_query))


async def etl_memes_from_raw_vk_posts() -> None:
    insert_query = """
        INSERT INTO meme (
            meme_source_id,
            raw_meme_id,
            caption,
            status,
            type,
            language_code,
            published_at
        )
        SELECT
            MRV.meme_source_id,
            MRV.id AS raw_meme_id,
            MRV.content AS caption,
            'created' AS status,
            'image' AS type,
            MS.language_code AS language_code,
            MRV.date AS published_at
        FROM meme_raw_vk AS MRV
        LEFT JOIN meme_source AS MS
            ON MS.id = MRV.meme_source_id
        WHERE 1=1
            -- only one attachment
            AND JSONB_ARRAY_LENGTH(MRV.media) = 1
            AND COALESCE(MRV.updated_at, MRV.created_at) >= NOW() - INTERVAL '24 hours'
        ON CONFLICT (meme_source_id, raw_meme_id)
        DO UPDATE
        SET
            status = CASE
                WHEN meme.status != 'broken_content_link'
                THEN meme.status
                ELSE 'created'
            END
    """
    await execute(text(insert_query))


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
            COALESCE(MRV.media->>0, MRT.media->0->>'url') content_url
        FROM meme M
        INNER JOIN meme_source MS
            ON MS.id = M.meme_source_id
        LEFT JOIN meme_raw_vk MRV
            ON MRV.id = M.raw_meme_id AND MS.type = 'vk'
        LEFT JOIN meme_raw_telegram MRT
            ON MRT.id = M.raw_meme_id AND MS.type = 'telegram'
        WHERE 1=1
            AND M.ocr_result IS NULL
            AND M.status != 'broken_content_link'
            AND M.type = 'image'
        ORDER BY M.created_at
    """
    return await fetch_all(text(select_query))


async def get_unloaded_tg_memes(limit) -> list[dict[str, Any]]:
    """Returns only MemeType.IMAGE memes"""
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


async def get_unloaded_vk_memes() -> list[dict[str, Any]]:
    "Returns only MemeType.IMAGE memes"
    select_query = f"""
        SELECT
            meme.id,
            '{MemeType.IMAGE}' AS type,
            meme_raw_vk.media->>0 content_url
        FROM meme
        INNER JOIN meme_source
            ON meme_source.id = meme.meme_source_id
            AND meme_source.type = '{MemeSourceType.VK.value}'
        INNER JOIN meme_raw_vk
            ON meme_raw_vk.id = meme.raw_meme_id
            AND meme_raw_vk.meme_source_id = meme.meme_source_id
        WHERE 1=1
            AND meme.telegram_file_id IS NULL;
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
              ) >= 0.9
            AND M.status != 'duplicate'
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
