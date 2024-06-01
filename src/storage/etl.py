from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from src.database import (
    execute,
    fetch_all,
    meme,
    meme_raw_ig,
    meme_raw_telegram,
    meme_raw_vk,
)
from src.storage.parsers.schemas import (
    IgPostParsingResult,
    TgChannelPostParsingResult,
    VkGroupPostParsingResult,
)


async def insert_parsed_posts_from_telegram(
    meme_source_id: int,
    telegram_posts: list[TgChannelPostParsingResult],
) -> None:
    # 1. find which memes are already in the database
    # 2. update existing memes
    # 3. insert new memes

    result = await fetch_all(
        select(meme_raw_telegram.c.post_id)
        .where(meme_raw_telegram.c.meme_source_id == meme_source_id)
        .where(
            meme_raw_telegram.c.post_id.in_([post.post_id for post in telegram_posts])
        )
    )
    post_ids_in_db = {row["post_id"] for row in result}

    posts_to_create = [
        post.model_dump() | {"meme_source_id": meme_source_id}
        for post in telegram_posts
        if post.post_id not in post_ids_in_db
    ]

    if len(posts_to_create) > 0:
        print(f"Going to insert {len(posts_to_create)} new posts.")
        await execute(insert(meme_raw_telegram).values(posts_to_create))

    posts_to_update = [
        post.model_dump()
        | {
            "meme_source_id": meme_source_id,
            "updated_at": datetime.now(timezone.utc).replace(tzinfo=None),
        }
        for post in telegram_posts
        if post.post_id in post_ids_in_db
    ]

    for post in posts_to_update:
        update_query = (
            meme_raw_telegram.update()
            .where(meme_raw_telegram.c.meme_source_id == meme_source_id)
            .where(meme_raw_telegram.c.post_id == post["post_id"])
            .values(post)
        )
        await execute(update_query)


async def insert_parsed_posts_from_vk(
    meme_source_id: int,
    vk_posts: list[VkGroupPostParsingResult],
) -> None:
    result = await fetch_all(
        select(meme_raw_vk.c.post_id)
        .where(meme_raw_vk.c.meme_source_id == meme_source_id)
        .where(meme_raw_vk.c.post_id.in_([post.post_id for post in vk_posts]))
    )
    post_ids_in_db = {row["post_id"] for row in result}

    posts_to_create = [
        post.model_dump() | {"meme_source_id": meme_source_id}
        for post in vk_posts
        if post.post_id not in post_ids_in_db
    ]

    if len(posts_to_create) > 0:
        print(f"Going to insert {len(posts_to_create)} new posts.")
        await execute(insert(meme_raw_vk).values(posts_to_create))

    posts_to_update = [
        post.model_dump()
        | {
            "meme_source_id": meme_source_id,
            "updated_at": datetime.now(timezone.utc).replace(tzinfo=None),
        }
        for post in vk_posts
        if post.post_id in post_ids_in_db
    ]

    for post in posts_to_update:
        update_query = (
            meme_raw_vk.update()
            .where(meme_raw_vk.c.meme_source_id == meme_source_id)
            .where(meme_raw_vk.c.post_id == post["post_id"])
            .values(post)
        )
        await execute(update_query)


async def insert_parsed_posts_from_ig(
    meme_source_id: int,
    vk_posts: list[IgPostParsingResult,],
) -> None:
    result = await fetch_all(
        select(meme_raw_ig.c.post_id)
        .where(meme_raw_ig.c.meme_source_id == meme_source_id)
        .where(meme_raw_ig.c.post_id.in_([post.post_id for post in vk_posts]))
    )
    post_ids_in_db = {row["post_id"] for row in result}

    posts_to_create = [
        post.model_dump() | {"meme_source_id": meme_source_id}
        for post in vk_posts
        if post.post_id not in post_ids_in_db
    ]

    if len(posts_to_create) > 0:
        print(f"Going to insert {len(posts_to_create)} new posts.")
        await execute(insert(vk_posts).values(posts_to_create))

    posts_to_update = [
        post.model_dump()
        | {
            "meme_source_id": meme_source_id,
            "updated_at": datetime.now(timezone.utc).replace(tzinfo=None),
        }
        for post in vk_posts
        if post.post_id in post_ids_in_db
    ]

    for post in posts_to_update:
        update_query = (
            meme_raw_vk.update()
            .where(meme_raw_vk.c.meme_source_id == meme_source_id)
            .where(meme_raw_vk.c.post_id == post["post_id"])
            .values(post)
        )
        await execute(update_query)


async def etl_memes_from_raw_telegram_posts() -> None:
    # get transformed posts
    # find ones that are already in the database
    # create rows and update rows
    transformed_memes = await fetch_all(
        text(
            """
                SELECT
                    DISTINCT ON (COALESCE(MRT.forwarded_url, random()::text))
                    MRT.meme_source_id,
                    MRT.id AS raw_meme_id,
                    MRT.content AS caption,
                    'created' AS status,
                    CASE
                        WHEN media->0->>'duration' IS NOT NULL THEN 'video'
                        WHEN media->0->>'url' LIKE '%.mp4%' THEN 'animation'
                        ELSE 'image'
                    END AS type,
                    MS.language_code AS language_code,
                    MRT.date AS published_at
                FROM meme_raw_telegram MRT
                INNER JOIN meme_source MS
                    ON MS.id = MRT.meme_source_id
                WHERE 1=1
                    AND JSONB_ARRAY_LENGTH(MRT.media) = 1 -- only one attachment
                    AND COALESCE(MRT.updated_at, MRT.created_at) >= NOW() - INTERVAL '24 hours'
            """  # noqa: E501
        )
    )

    # find rows which already exist in db by two index columns:
    # meme_source_id and raw_meme_id
    # so we can update existing rows and create new ones

    # join two tables meme_raw_telegram and meme to get
    # the meme_source_id and raw_meme_id pairs
    # which are not present in memes table.
    # That will indicate that we need to create new rows

    memes_not_in_memes_table = await fetch_all(
        text(
            """
                SELECT
                    MRT.meme_source_id,
                    MRT.id AS raw_meme_id
                FROM meme_raw_telegram MRT
                LEFT JOIN meme
                    ON meme.meme_source_id = MRT.meme_source_id
                    AND meme.raw_meme_id = MRT.id
                WHERE 1=1
                    AND meme.meme_source_id IS NULL
                    AND meme.raw_meme_id IS NULL
                    AND JSONB_ARRAY_LENGTH(MRT.media) = 1
            """
        )
    )

    await update_or_create_memes(transformed_memes, memes_not_in_memes_table)


async def etl_memes_from_raw_vk_posts() -> None:
    transformed_memes = await fetch_all(
        text(
            """
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
            """  # noqa: E501
        )
    )

    memes_not_in_memes_table = await fetch_all(
        text(
            """
                SELECT
                    MRV.meme_source_id,
                    MRV.id AS raw_meme_id
                FROM meme_raw_vk MRV
                LEFT JOIN meme
                    ON meme.meme_source_id = MRV.meme_source_id
                    AND meme.raw_meme_id = MRV.id
                WHERE 1=1
                    AND meme.meme_source_id IS NULL
                    AND meme.raw_meme_id IS NULL
                    AND JSONB_ARRAY_LENGTH(MRV.media) = 1
            """
        )
    )

    await update_or_create_memes(transformed_memes, memes_not_in_memes_table)


async def etl_memes_from_raw_ig_posts() -> None:
    transformed_memes = await fetch_all(
        text(
            """
                SELECT
                    MRI.meme_source_id,
                    MRI.id AS raw_meme_id,
                    CASE
                        WHEN media->0->>'url' LIKE '%.mp4%' THEN 'video'
                        ELSE 'image'
                    END AS type,
                    'created' AS status,
                    MS.language_code,
                    MRI.published_at
                FROM meme_raw_ig AS MRI
                LEFT JOIN meme_source AS MS
                    ON MS.id = MRI.meme_source_id
                WHERE 1=1
                    AND COALESCE(MRI.updated_at, MRI.created_at) >= NOW() - INTERVAL '24 hours'
            """  # noqa: E501
        )
    )

    memes_not_in_memes_table = await fetch_all(
        text(
            """
                SELECT
                    MRI.meme_source_id,
                    MRI.id AS raw_meme_id
                FROM meme_raw_ig MRI
                LEFT JOIN meme
                    ON meme.meme_source_id = MRI.meme_source_id
                    AND meme.raw_meme_id = MRI.id
                WHERE 1=1
                    AND meme.meme_source_id IS NULL
                    AND meme.raw_meme_id IS NULL
                    AND JSONB_ARRAY_LENGTH(MRI.media) = 1
            """
        )
    )

    await update_or_create_memes(transformed_memes, memes_not_in_memes_table)


async def update_or_create_memes(transformed_memes, memes_not_in_memes_table):
    create_these_memes = [
        m
        for m in transformed_memes
        if (m["meme_source_id"], m["raw_meme_id"]) in memes_not_in_memes_table
    ]
    if len(create_these_memes):
        await execute(insert(meme).values(create_these_memes))

    update_these_memes = [
        m
        | {"status": "created" if m["status"] == "broken_content_link" else m["status"]}
        for m in transformed_memes
        if (m["meme_source_id"], m["raw_meme_id"]) not in memes_not_in_memes_table
    ]

    for m in update_these_memes:
        await execute(
            meme.update()
            .where(meme.c.meme_source_id == m["meme_source_id"])
            .where(meme.c.raw_meme_id == m["raw_meme_id"])
            .values(m),
        )
