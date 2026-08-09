from datetime import datetime
from typing import Any

from sqlalchemy import nulls_first, select, text

from src.database import (
    fetch_all,
    fetch_one,
    meme,
    meme_source,
    meme_source_stats,
)
from src.storage.constants import (
    MemeSourceStatus,
    MemeSourceType,
    MemeStatus,
)

STALE_SOURCE_SNOOZE_AFTER_DAYS = 7


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


async def update_meme_source(meme_source_id: int, **kwargs) -> dict[str, Any] | None:
    update_query = (
        meme_source.update()
        .where(meme_source.c.id == meme_source_id)
        .values(**kwargs)
        .returning(meme_source)
    )
    return await fetch_one(update_query)


async def auto_snooze_stale_sources(
    stale_after_days: int = STALE_SOURCE_SNOOZE_AFTER_DAYS,
    limit: int = 50,
    meme_source_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """
    Snooze parsing-enabled sources that have produced no raw posts for a full stale window.

    This catches sources that no longer reach maybe_auto_snooze_source because the
    parser is gone, disabled, or failing before parsed_at can advance. The 7-day
    floor keeps one quiet day from snoozing a valid low-volume source.
    """
    query = text(
        """
        WITH raw_activity AS (
            SELECT
                meme_source_id,
                MAX(created_at) AS last_raw_insert_at
            FROM (
                SELECT meme_source_id, created_at FROM meme_raw_telegram
                UNION ALL
                SELECT meme_source_id, created_at FROM meme_raw_vk
                UNION ALL
                SELECT meme_source_id, created_at FROM meme_raw_ig
            ) raw_posts
            GROUP BY meme_source_id
        ),
        stale_candidates AS (
            SELECT
                ms.id,
                ms.type,
                ms.url,
                ms.parsed_at,
                raw_activity.last_raw_insert_at
            FROM meme_source ms
            LEFT JOIN raw_activity
                ON raw_activity.meme_source_id = ms.id
            WHERE ms.status = 'parsing_enabled'
              AND (
                  NOT :filter_meme_source_ids
                  OR ms.id = ANY(:meme_source_ids)
              )
              AND ms.created_at < NOW() - make_interval(days => :stale_after_days)
              AND (
                  ms.parsed_at IS NULL
                  OR ms.parsed_at < NOW() - make_interval(days => :stale_after_days)
              )
              AND (
                  raw_activity.last_raw_insert_at IS NULL
                  OR raw_activity.last_raw_insert_at
                      < NOW() - make_interval(days => :stale_after_days)
              )
            ORDER BY ms.parsed_at NULLS FIRST, ms.id
            LIMIT :limit
        ),
        updated_sources AS (
            UPDATE meme_source ms
            SET
                status = 'snoozed',
                data = COALESCE(ms.data, '{}'::jsonb) || jsonb_build_object(
                    'snoozed_reason',
                    'stale_no_raw_posts_7d',
                    'snoozed_at',
                    to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US'),
                    'stale_after_days',
                    :stale_after_days,
                    'stale_last_parsed_at',
                    stale_candidates.parsed_at,
                    'stale_last_raw_insert_at',
                    stale_candidates.last_raw_insert_at
                )
            FROM stale_candidates
            WHERE ms.id = stale_candidates.id
            RETURNING
                ms.id,
                ms.type,
                ms.url,
                ms.parsed_at,
                stale_candidates.last_raw_insert_at
        ),
        updated_memes AS (
            UPDATE meme m
            SET status = 'snoozed'
            FROM updated_sources
            WHERE m.meme_source_id = updated_sources.id
              AND m.status = 'ok'
            RETURNING m.id
        )
        SELECT
            id,
            type,
            url,
            parsed_at,
            last_raw_insert_at
        FROM updated_sources
        """
    )
    return await fetch_all(
        query,
        {
            "stale_after_days": int(stale_after_days),
            "limit": int(limit),
            "filter_meme_source_ids": meme_source_ids is not None,
            "meme_source_ids": meme_source_ids or [],
        },
    )


async def maybe_auto_snooze_source(
    meme_source_id: int,
    new_posts_count: int,
) -> str | None:
    """
    Check auto-snooze criteria after a parse attempt.
    Snoozes the source if any criterion is met:
      1. 3 consecutive parse attempts returned 0 posts.
      2. like_rate < 10% with at least 100 total reactions.
      3a. ad_rate >= 80% over rolling 7d window with >= 10 processed memes
          (early-kill for extreme pumpers).
      3b. ad_rate > 30% over rolling 7d window with >= 30 processed memes.
    Returns the snooze reason string if snoozed, None otherwise.
    """
    source = await fetch_one(select(meme_source).where(meme_source.c.id == meme_source_id))
    if not source or source["status"] != MemeSourceStatus.PARSING_ENABLED.value:
        return None

    current_data = source["data"] or {}
    now_iso = datetime.utcnow().isoformat()

    # Track consecutive empty parses
    if new_posts_count == 0:
        consecutive = current_data.get("consecutive_empty_parses", 0) + 1
    else:
        consecutive = 0

    updated_data = {**current_data, "consecutive_empty_parses": consecutive}

    # Criterion 1: 3+ consecutive empty parses
    if consecutive >= 3:
        await update_meme_source(
            meme_source_id,
            status=MemeSourceStatus.SNOOZED.value,
            data={**updated_data, "snoozed_reason": "no_posts_3x", "snoozed_at": now_iso},
        )
        return "no_posts_3x"

    # Criterion 2: like_rate < 10% (min 100 reactions for a meaningful sample)
    stats = await fetch_one(
        select(meme_source_stats).where(meme_source_stats.c.meme_source_id == meme_source_id)
    )
    if stats is not None:
        total = stats["nlikes"] + stats["ndislikes"]
        if total >= 100 and stats["nlikes"] / total < 0.10:
            await update_meme_source(
                meme_source_id,
                status=MemeSourceStatus.SNOOZED.value,
                data={
                    **updated_data,
                    "snoozed_reason": "low_like_rate",
                    "snoozed_at": now_iso,
                },
            )
            return "low_like_rate"

    # Criterion 3: rolling 7d ad_rate > 30% (min 30 processed memes for sample).
    # n_processed = "memes the source actually delivered" — excludes pipeline failures
    # and pre-pipeline states. Includes 'published' so cross-posted ok memes still count
    # (otherwise high-quality sources would shrink the denominator and false-positive snooze).
    ad_stats = await fetch_one(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'ad')::float AS n_ads,
                COUNT(*) FILTER (
                    WHERE status NOT IN (
                        'created',
                        'broken_content_link',
                        'expired_content_link',
                        'rejected',
                        'waiting_review',
                        'snoozed'
                    )
                ) AS n_processed
            FROM meme
            WHERE meme_source_id = :sid
              AND created_at > NOW() - INTERVAL '7 days'
            """
        ),
        {"sid": meme_source_id},
    )
    if ad_stats and ad_stats["n_processed"] >= 10:
        ad_rate = ad_stats["n_ads"] / ad_stats["n_processed"]
        # Criterion 3a: pure-pumper early-kill. A 100%-ad source has no legitimate
        # signal regardless of volume; the 30-meme floor only protects against
        # noise, which doesn't apply at >=80% ad_rate.
        if ad_rate >= 0.80:
            await update_meme_source(
                meme_source_id,
                status=MemeSourceStatus.SNOOZED.value,
                data={
                    **updated_data,
                    "snoozed_reason": "extreme_ad_rate",
                    "snoozed_at": now_iso,
                },
            )
            return "extreme_ad_rate"
        # Criterion 3b: standard high-ad-rate gate.
        if ad_stats["n_processed"] >= 30 and ad_rate > 0.30:
            await update_meme_source(
                meme_source_id,
                status=MemeSourceStatus.SNOOZED.value,
                data={
                    **updated_data,
                    "snoozed_reason": "high_ad_rate",
                    "snoozed_at": now_iso,
                },
            )
            return "high_ad_rate"

    # No snooze: persist updated counter if it changed
    if updated_data != current_data:
        await update_meme_source(meme_source_id, data=updated_data)

    return None


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


async def get_unloaded_tg_memes(
    limit: int,
    meme_source_ids: list[int] | None = None,
    *,
    fresh_only: bool = True,
) -> list[dict[str, Any]]:
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
            AND meme_source.status = 'parsing_enabled'
        INNER JOIN meme_raw_telegram MRT
            ON MRT.id = meme.raw_meme_id
            AND MRT.meme_source_id = meme.meme_source_id
        WHERE 1=1
            AND (
                meme.telegram_file_id IS NULL
                OR meme.status = 'broken_content_link'
            )
            AND MRT.media->0->>'url' IS NOT NULL
            AND (
                NOT :filter_meme_source_ids
                OR meme.meme_source_id = ANY(:meme_source_ids)
            )
            AND (
                NOT :fresh_only
                OR COALESCE(MRT.updated_at, MRT.created_at) >= NOW() - INTERVAL '24 hours'
            )
        ORDER BY meme.published_at DESC
        LIMIT {limit}
    """
    return await fetch_all(
        text(select_query),
        {
            "filter_meme_source_ids": meme_source_ids is not None,
            "meme_source_ids": meme_source_ids or [],
            "fresh_only": fresh_only,
        },
    )


async def get_unloaded_vk_memes(
    limit: int,
    meme_source_ids: list[int] | None = None,
    *,
    fresh_only: bool = True,
) -> list[dict[str, Any]]:
    """Returns VK memes not yet uploaded to Telegram storage.

    Parity with TG unload path:
    - only ``parsing_enabled`` sources
    - retry ``broken_content_link`` (ETL already resets → created periodically)
    - optional fresh window on raw post timestamps
    """
    select_query = f"""
        SELECT
            meme.id,
            meme.type,
            CASE
                WHEN JSONB_TYPEOF(meme_raw_vk.media) = 'array'
                THEN meme_raw_vk.media->>0
                ELSE meme_raw_vk.media::text
            END AS content_url
        FROM meme
        INNER JOIN meme_source
            ON meme_source.id = meme.meme_source_id
            AND meme_source.type = '{MemeSourceType.VK.value}'
            AND meme_source.status = '{MemeSourceStatus.PARSING_ENABLED.value}'
        INNER JOIN meme_raw_vk
            ON meme_raw_vk.id = meme.raw_meme_id
            AND meme_raw_vk.meme_source_id = meme.meme_source_id
        WHERE 1=1
            AND (
                meme.telegram_file_id IS NULL
                OR meme.status = 'broken_content_link'
            )
            AND (
                NOT :filter_meme_source_ids
                OR meme.meme_source_id = ANY(:meme_source_ids)
            )
            AND (
                NOT :fresh_only
                OR COALESCE(meme_raw_vk.updated_at, meme_raw_vk.created_at)
                    >= NOW() - INTERVAL '24 hours'
            )
        ORDER BY meme.published_at DESC
        LIMIT {int(limit)}
    """
    return await fetch_all(
        text(select_query),
        {
            "filter_meme_source_ids": meme_source_ids is not None,
            "meme_source_ids": meme_source_ids or [],
            "fresh_only": fresh_only,
        },
    )


async def update_meme_status_of_ready_memes(
    meme_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Changes the status of memes to 'ok' if they are ready to be published."""
    if meme_ids is not None and len(meme_ids) == 0:
        return []

    update_query = (
        meme.update()
        .where(meme.c.status == MemeStatus.CREATED)
        .where(meme.c.telegram_file_id.is_not(None))
        .where(meme.c.duplicate_of.is_(None))
        .values(status=MemeStatus.OK)
        .returning(meme)
    )
    if meme_ids is not None:
        update_query = update_query.where(meme.c.id.in_(meme_ids))
    return await fetch_all(update_query)
