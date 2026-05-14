import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from src.database import (
    execute,
    fetch_all,
    meme,
    meme_raw_telegram,
    meme_raw_vk,
    meme_source_candidate,
)
from src.storage.constants import MemeSourceType
from src.storage.parsers.schemas import (
    TgChannelPostParsingResult,
    VkGroupPostParsingResult,
)

_TG_FORWARD_URL_PATTERN = re.compile(r"^https?://t\.me/(?:s/)?([a-zA-Z0-9_]+)(?:/\d+)?/?$")


def normalize_telegram_channel_url(forwarded_url: str) -> Optional[str]:
    """Strip post id, lowercase username, return canonical https://t.me/<channel>.

    Returns None for joinchat/private/invite links and anything we can't safely
    promote to a public channel source.
    """
    if not forwarded_url:
        return None
    # Drop query string + fragment so `?utm=...` or `#anchor` don't break the
    # regex and so manual moderator entries collapse onto the same canonical
    # form as discovery-pipeline candidates.
    cleaned = forwarded_url.strip().split("?", 1)[0].split("#", 1)[0]
    match = _TG_FORWARD_URL_PATTERN.match(cleaned)
    if not match:
        return None
    username = match.group(1).lower()
    # private/invite links and bot-update aliases aren't usable as sources
    if username in {"joinchat", "addstickers", "share", "proxy"}:
        return None
    return f"https://t.me/{username}"


async def insert_parsed_posts_from_telegram(
    meme_source_id: int,
    telegram_posts: list[TgChannelPostParsingResult],
    *,
    discover_candidates: bool = True,
) -> None:
    # 1. find which memes are already in the database
    # 2. update existing memes
    # 3. insert new memes

    result = await fetch_all(
        select(meme_raw_telegram.c.post_id)
        .where(meme_raw_telegram.c.meme_source_id == meme_source_id)
        .where(meme_raw_telegram.c.post_id.in_([post.post_id for post in telegram_posts]))
    )
    post_ids_in_db = {row["post_id"] for row in result}

    new_posts = [post for post in telegram_posts if post.post_id not in post_ids_in_db]

    posts_to_create = [post.model_dump() | {"meme_source_id": meme_source_id} for post in new_posts]

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

    if discover_candidates:
        # Only newly-inserted posts feed candidate discovery; otherwise every parse
        # cycle re-counts the same forwarded URLs and corrupts times_forwarded.
        await discover_source_candidates_from_telegram_posts(meme_source_id, new_posts)


async def discover_source_candidates_from_telegram_posts(
    meme_source_id: int,
    telegram_posts: list[TgChannelPostParsingResult],
) -> None:
    """Upsert forward-source candidates from a parsed TG batch.

    Conservative-by-default: candidates land with status='discovered' and never
    auto-promote to `meme_source`. Skips URLs already tracked as sources to
    keep the moderator queue clean. See FFM-933.
    """
    seen_post_ids: dict[str, int] = {}  # canonical_url -> first sample TG post id
    increments: dict[str, int] = {}
    for post in telegram_posts:
        canonical = normalize_telegram_channel_url(post.forwarded_url or "")
        if canonical is None:
            continue
        increments[canonical] = increments.get(canonical, 0) + 1
        seen_post_ids.setdefault(canonical, post.post_id)

    if not increments:
        return

    # Drop any URL that is already a tracked source — no point queueing it for
    # moderator promotion if we're already parsing it.
    existing_rows = await fetch_all(
        text("SELECT url FROM meme_source WHERE url = ANY(:urls)"),
        {"urls": list(increments.keys())},
    )
    already_tracked = {row["url"] for row in existing_rows}

    for canonical, delta in increments.items():
        if canonical in already_tracked:
            continue
        stmt = (
            insert(meme_source_candidate)
            .values(
                {
                    "type": MemeSourceType.TELEGRAM.value,
                    "url": canonical,
                    "status": "discovered",
                    "times_forwarded": delta,
                    "sample_meme_source_id": meme_source_id,
                    "sample_meme_raw_telegram_post_id": seen_post_ids.get(canonical),
                }
            )
            .on_conflict_do_update(
                index_elements=[meme_source_candidate.c.url],
                set_={
                    "times_forwarded": (meme_source_candidate.c.times_forwarded + delta),
                    "last_seen_at": text("now()"),
                    "updated_at": text("now()"),
                },
            )
        )
        await execute(stmt)


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


async def etl_memes_from_raw_telegram_posts(
    meme_source_ids: list[int] | None = None,
    *,
    fresh_only: bool = True,
) -> None:
    # get transformed posts
    # find ones that are already in the database
    # create rows and update rows
    #
    # Engagement filter: skip posts with views < 30% of their source's median.
    # This filters low-quality posts (likely ads or junk) before they enter the
    # meme table. Posts with 0 views (views not available) are kept.
    transformed_memes = await fetch_all(
        text(
            """
                WITH source_medians AS (
                    SELECT
                        meme_source_id,
                        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY views) AS median_views
                    FROM meme_raw_telegram
                    WHERE COALESCE(updated_at, created_at) >= NOW() - INTERVAL '24 hours'
                      AND views > 0
                    GROUP BY meme_source_id
                )
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
                LEFT JOIN source_medians SM
                    ON SM.meme_source_id = MRT.meme_source_id
                WHERE 1=1
                    AND MS.status = 'parsing_enabled'
                    AND (
                        NOT :filter_meme_source_ids
                        OR MRT.meme_source_id = ANY(:meme_source_ids)
                    )
                    AND JSONB_ARRAY_LENGTH(
                        CASE
                            WHEN JSONB_TYPEOF(MRT.media) = 'array' THEN MRT.media
                            ELSE '[]'::jsonb
                        END
                    ) = 1 -- only one attachment
                    AND (
                        NOT :fresh_only
                        OR COALESCE(MRT.updated_at, MRT.created_at) >= NOW() - INTERVAL '24 hours'
                    )
                    AND (
                        MRT.views = 0
                        OR SM.median_views IS NULL
                        OR MRT.views >= SM.median_views * 0.3
                    )
                    -- Ad filter: skip posts with outlinks + below-median views
                    AND NOT (
                        JSONB_ARRAY_LENGTH(
                            CASE
                                WHEN JSONB_TYPEOF(COALESCE(MRT.out_links, '[]'::jsonb)) = 'array'
                                THEN COALESCE(MRT.out_links, '[]'::jsonb)
                                ELSE '[]'::jsonb
                            END
                        ) > 0
                        AND MRT.views > 0
                        AND SM.median_views IS NOT NULL
                        AND MRT.views < SM.median_views * 0.5
                    )
            """  # noqa: E501
        ),
        {
            "filter_meme_source_ids": meme_source_ids is not None,
            "meme_source_ids": meme_source_ids or [],
            "fresh_only": fresh_only,
        },
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
                INNER JOIN meme_source MS
                    ON MS.id = MRT.meme_source_id
                LEFT JOIN meme
                    ON meme.meme_source_id = MRT.meme_source_id
                    AND meme.raw_meme_id = MRT.id
                WHERE 1=1
                    AND MS.status = 'parsing_enabled'
                    AND (
                        NOT :filter_meme_source_ids
                        OR MRT.meme_source_id = ANY(:meme_source_ids)
                    )
                    AND (
                        NOT :fresh_only
                        OR COALESCE(MRT.updated_at, MRT.created_at) >= NOW() - INTERVAL '24 hours'
                    )
                    AND meme.meme_source_id IS NULL
                    AND meme.raw_meme_id IS NULL
                    AND JSONB_ARRAY_LENGTH(
                        CASE
                            WHEN JSONB_TYPEOF(MRT.media) = 'array' THEN MRT.media
                            ELSE '[]'::jsonb
                        END
                    ) = 1
            """
        ),
        {
            "filter_meme_source_ids": meme_source_ids is not None,
            "meme_source_ids": meme_source_ids or [],
            "fresh_only": fresh_only,
        },
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


async def update_or_create_memes(transformed_memes, memes_not_in_memes_table):
    create_these_memes = [
        m
        for m in transformed_memes
        if {"meme_source_id": m["meme_source_id"], "raw_meme_id": m["raw_meme_id"]}
        in memes_not_in_memes_table
    ]
    if len(create_these_memes):
        stmt = (
            insert(meme)
            .values(create_these_memes)
            .on_conflict_do_nothing(
                index_elements=["meme_source_id", "raw_meme_id"],
            )
        )
        await execute(stmt)

    update_these_memes = [
        m
        for m in transformed_memes
        if {"meme_source_id": m["meme_source_id"], "raw_meme_id": m["raw_meme_id"]}
        not in memes_not_in_memes_table
    ]

    # Only update metadata — never overwrite status on existing memes.
    # This prevents resetting ok/duplicate memes back to 'created'.
    for m in update_these_memes:
        await execute(
            meme.update()
            .where(meme.c.meme_source_id == m["meme_source_id"])
            .where(meme.c.raw_meme_id == m["raw_meme_id"])
            .values(
                caption=m.get("caption"),
                language_code=m.get("language_code"),
                published_at=m.get("published_at"),
            ),
        )

    # Retry broken uploads: reset broken_content_link → created so the upload
    # pipeline picks them up again. Excludes Instagram — the IG parser was
    # removed and existing IG memes have stale CDN URLs that will never load.
    await execute(
        text(
            """
            UPDATE meme
            SET status = 'created'
            FROM meme_source
            WHERE meme.status = 'broken_content_link'
              AND meme_source.id = meme.meme_source_id
              AND meme_source.type != 'instagram'
            """
        )
    )
