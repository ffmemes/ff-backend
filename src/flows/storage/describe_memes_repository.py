from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from src.database import execute, fetch_all, fetch_one, meme
from src.flows.storage.openrouter_vision import VISION_MODELS

KNOWN_LANGUAGES = {
    "ru",
    "en",
    "uk",
    "es",
    "fa",
    "pl",
    "hi",
    "am",
    "de",
    "fr",
    "pt-br",
    "ar",
    "uz",
}

RECENT_WINDOW_DAYS = 7
# The delivery-event index is ordered by sent_at, so this bounded lookback finds
# images that users are seeing now without aggregating the complete reaction
# history on every 15-minute OCR run.
RECENT_DELIVERY_SCAN_MINIMUM = 500


def _describe_queue_limits(limit: int) -> dict[str, int]:
    """Reserve a small, explicit share of each OCR batch for every queue tier.

    The deployed batch size is nine: five recent deliveries, two uploads, one
    other fresh image, and one oldest pending image.  The calculation keeps the
    same proportions for manual or catch-up invocations with a different limit.
    """
    if limit < 1:
        return {"recent_served": 0, "recent_uploads": 0, "fresh": 0, "oldest": 0}

    oldest = limit // 9
    remaining = limit - oldest
    recent_served = (remaining * 5) // 8
    recent_uploads = (remaining * 2) // 8
    fresh = remaining - recent_served - recent_uploads
    return {
        "recent_served": recent_served,
        "recent_uploads": recent_uploads,
        "fresh": fresh,
        "oldest": oldest,
    }


def _text_or_empty(value: Any) -> str:
    return value if isinstance(value, str) else ""


async def get_memes_to_describe(limit: int = 30) -> list[dict[str, Any]]:
    """Get image memes without descriptions.

    Priority order:
    1. Recent user uploads — enables dedup before they spread further
    2. Images actually sent to users recently — protects the active feed
    3. Freshly parsed images — keeps ingestion close to real time
    4. One oldest-pending fairness slot per nine items — prevents starvation

    Unused upload capacity is reassigned to recent deliveries, then unused
    recent-delivery capacity is reassigned to fresh images.  The delivery tier
    reads only the newest indexed events, never an aggregate over all reactions.

    Skips memes that have failed 3+ times (tracked in ocr_result.describe_failures).
    """
    limits = _describe_queue_limits(limit)
    recent_delivery_scan_limit = max(
        RECENT_DELIVERY_SCAN_MINIMUM,
        limits["recent_served"] * 100,
    )
    query = text(
        """
        WITH recent_uploads AS MATERIALIZED (
            SELECT
                M.id,
                M.telegram_file_id,
                M.ocr_result,
                M.status,
                M.language_code,
                M.created_at,
                0 AS queue_priority
            FROM meme M
            INNER JOIN meme_source SRC ON SRC.id = M.meme_source_id
            WHERE SRC.type = 'user upload'
                AND M.created_at >= now() - (:recent_window_days * INTERVAL '1 day')
                AND M.type = 'image'
                AND M.status = 'ok'
                AND M.telegram_file_id IS NOT NULL
                AND (M.ocr_result IS NULL OR M.ocr_result->>'description' IS NULL)
                AND COALESCE((M.ocr_result->>'describe_failures')::int, 0) < 3
            ORDER BY M.created_at DESC
            LIMIT :recent_uploads_limit
        ),
        recent_delivery_events AS MATERIALIZED (
            SELECT R.meme_id, R.sent_at
            FROM user_meme_reaction R
            WHERE R.sent_at >= now() - (:recent_window_days * INTERVAL '1 day')
            ORDER BY R.sent_at DESC
            LIMIT :recent_delivery_scan_limit
        ),
        recent_served AS MATERIALIZED (
            SELECT DISTINCT ON (meme_id) meme_id, sent_at AS last_sent_at
            FROM recent_delivery_events
            ORDER BY meme_id, sent_at DESC
        ),
        selected_recent_served AS MATERIALIZED (
            SELECT
                M.id,
                M.telegram_file_id,
                M.ocr_result,
                M.status,
                M.language_code,
                RS.last_sent_at AS queue_time,
                1 AS queue_priority
            FROM recent_served RS
            INNER JOIN meme M ON M.id = RS.meme_id
            WHERE M.type = 'image'
                AND M.status = 'ok'
                AND M.telegram_file_id IS NOT NULL
                AND (M.ocr_result IS NULL OR M.ocr_result->>'description' IS NULL)
                AND COALESCE((M.ocr_result->>'describe_failures')::int, 0) < 3
                AND NOT EXISTS (SELECT 1 FROM recent_uploads U WHERE U.id = M.id)
            ORDER BY RS.last_sent_at DESC
            LIMIT (
                :recent_served_limit
                + :recent_uploads_limit
                - (SELECT COUNT(*) FROM recent_uploads)
            )
        ),
        selected_fresh AS MATERIALIZED (
            SELECT
                M.id,
                M.telegram_file_id,
                M.ocr_result,
                M.status,
                M.language_code,
                M.created_at AS queue_time,
                2 AS queue_priority
            FROM meme M
            LEFT JOIN meme_source SRC ON SRC.id = M.meme_source_id
            WHERE M.created_at >= now() - (:recent_window_days * INTERVAL '1 day')
                AND SRC.type IS DISTINCT FROM 'user upload'
                AND M.type = 'image'
                AND M.status = 'ok'
                AND M.telegram_file_id IS NOT NULL
                AND (M.ocr_result IS NULL OR M.ocr_result->>'description' IS NULL)
                AND COALESCE((M.ocr_result->>'describe_failures')::int, 0) < 3
                AND NOT EXISTS (SELECT 1 FROM recent_uploads U WHERE U.id = M.id)
                AND NOT EXISTS (SELECT 1 FROM selected_recent_served S WHERE S.id = M.id)
                AND NOT EXISTS (SELECT 1 FROM recent_served RS WHERE RS.meme_id = M.id)
            ORDER BY M.created_at DESC
            LIMIT (
                :fresh_limit
                + GREATEST(
                    0,
                    :recent_served_limit
                    + :recent_uploads_limit
                    - (SELECT COUNT(*) FROM recent_uploads)
                    - (SELECT COUNT(*) FROM selected_recent_served)
                )
            )
        ),
        selected_oldest AS MATERIALIZED (
            SELECT
                M.id,
                M.telegram_file_id,
                M.ocr_result,
                M.status,
                M.language_code,
                M.created_at AS queue_time,
                3 AS queue_priority
            FROM meme M
            WHERE M.created_at < now() - (:recent_window_days * INTERVAL '1 day')
                AND M.type = 'image'
                AND M.status = 'ok'
                AND M.telegram_file_id IS NOT NULL
                AND (M.ocr_result IS NULL OR M.ocr_result->>'description' IS NULL)
                AND COALESCE((M.ocr_result->>'describe_failures')::int, 0) < 3
                AND NOT EXISTS (SELECT 1 FROM recent_uploads U WHERE U.id = M.id)
                AND NOT EXISTS (SELECT 1 FROM selected_recent_served S WHERE S.id = M.id)
                AND NOT EXISTS (SELECT 1 FROM selected_fresh F WHERE F.id = M.id)
            ORDER BY M.created_at ASC
            LIMIT (
                :oldest_limit
                + GREATEST(
                    0,
                    :recent_served_limit
                    + :recent_uploads_limit
                    + :fresh_limit
                    - (SELECT COUNT(*) FROM recent_uploads)
                    - (SELECT COUNT(*) FROM selected_recent_served)
                    - (SELECT COUNT(*) FROM selected_fresh)
                )
            )
        ),
        selected_active_backfill AS MATERIALIZED (
            SELECT
                id, telegram_file_id, ocr_result, status, language_code, queue_time, queue_priority
            FROM (
                SELECT
                    M.id,
                    M.telegram_file_id,
                    M.ocr_result,
                    M.status,
                    M.language_code,
                    RS.last_sent_at AS queue_time,
                    1 AS queue_priority
                FROM recent_served RS
                INNER JOIN meme M ON M.id = RS.meme_id
                WHERE M.type = 'image'
                    AND M.status = 'ok'
                    AND M.telegram_file_id IS NOT NULL
                    AND (M.ocr_result IS NULL OR M.ocr_result->>'description' IS NULL)
                    AND COALESCE((M.ocr_result->>'describe_failures')::int, 0) < 3
                    AND NOT EXISTS (SELECT 1 FROM recent_uploads U WHERE U.id = M.id)
                    AND NOT EXISTS (SELECT 1 FROM selected_recent_served S WHERE S.id = M.id)
                    AND NOT EXISTS (SELECT 1 FROM selected_fresh F WHERE F.id = M.id)
                    AND NOT EXISTS (SELECT 1 FROM selected_oldest O WHERE O.id = M.id)
                UNION ALL
                SELECT
                    M.id,
                    M.telegram_file_id,
                    M.ocr_result,
                    M.status,
                    M.language_code,
                    M.created_at AS queue_time,
                    2 AS queue_priority
                FROM meme M
                LEFT JOIN meme_source SRC ON SRC.id = M.meme_source_id
                WHERE M.created_at >= now() - (:recent_window_days * INTERVAL '1 day')
                    AND SRC.type IS DISTINCT FROM 'user upload'
                    AND M.type = 'image'
                    AND M.status = 'ok'
                    AND M.telegram_file_id IS NOT NULL
                    AND (M.ocr_result IS NULL OR M.ocr_result->>'description' IS NULL)
                    AND COALESCE((M.ocr_result->>'describe_failures')::int, 0) < 3
                    AND NOT EXISTS (SELECT 1 FROM recent_served RS WHERE RS.meme_id = M.id)
                    AND NOT EXISTS (SELECT 1 FROM recent_uploads U WHERE U.id = M.id)
                    AND NOT EXISTS (SELECT 1 FROM selected_recent_served S WHERE S.id = M.id)
                    AND NOT EXISTS (SELECT 1 FROM selected_fresh F WHERE F.id = M.id)
                    AND NOT EXISTS (SELECT 1 FROM selected_oldest O WHERE O.id = M.id)
            ) active_candidates
            ORDER BY queue_priority, queue_time DESC
            LIMIT (
                :limit
                - (SELECT COUNT(*) FROM recent_uploads)
                - (SELECT COUNT(*) FROM selected_recent_served)
                - (SELECT COUNT(*) FROM selected_fresh)
                - (SELECT COUNT(*) FROM selected_oldest)
            )
        )
        SELECT id, telegram_file_id, ocr_result, status, language_code
        FROM (
            SELECT
                id, telegram_file_id, ocr_result, status, language_code,
                queue_priority, created_at AS queue_time
            FROM recent_uploads
            UNION ALL
            SELECT
                id, telegram_file_id, ocr_result, status, language_code,
                queue_priority, queue_time
            FROM selected_recent_served
            UNION ALL
            SELECT
                id, telegram_file_id, ocr_result, status, language_code,
                queue_priority, queue_time
            FROM selected_fresh
            UNION ALL
            SELECT
                id, telegram_file_id, ocr_result, status, language_code,
                queue_priority, queue_time
            FROM selected_oldest
            UNION ALL
            SELECT
                id, telegram_file_id, ocr_result, status, language_code,
                queue_priority, queue_time
            FROM selected_active_backfill
        ) queued
        ORDER BY queue_priority, queue_time DESC
    """
    ).bindparams(
        limit=limit,
        recent_window_days=RECENT_WINDOW_DAYS,
        recent_delivery_scan_limit=recent_delivery_scan_limit,
        recent_served_limit=limits["recent_served"],
        recent_uploads_limit=limits["recent_uploads"],
        fresh_limit=limits["fresh"],
        oldest_limit=limits["oldest"],
    )

    return await fetch_all(query)


async def increment_describe_failures(
    meme_id: int,
    existing_ocr: dict[str, Any],
    reason: str,
) -> None:
    """Track describe failures in ocr_result so permanently broken memes get skipped."""
    failures = int(existing_ocr.get("describe_failures", 0)) + 1
    merged = {**existing_ocr, "describe_failures": failures, "last_failure_reason": reason}
    update_query = meme.update().where(meme.c.id == meme_id).values(ocr_result=merged)
    await execute(update_query)


async def save_meme_description(
    meme_id: int,
    existing_ocr: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    ocr_text = _text_or_empty(result.get("ocr_text"))
    description = _text_or_empty(result.get("description"))
    language = _text_or_empty(result.get("language"))
    model_used = result.get("__model", VISION_MODELS[0])

    merged = {
        **existing_ocr,
        "model": model_used,
        "calculated_at": datetime.now(timezone.utc).isoformat(),
        "raw_result": {
            "ocr_text": ocr_text,
            "description": description,
            "language": language,
        },
        "description": description,
    }

    if not existing_ocr.get("text"):
        merged["text"] = ocr_text

    update_kwargs: dict[str, Any] = {"ocr_result": merged}
    language_code = language.strip().lower()
    if language_code in KNOWN_LANGUAGES:
        update_kwargs["language_code"] = language_code

    update_query = meme.update().where(meme.c.id == meme_id).values(**update_kwargs).returning(meme)
    await fetch_one(update_query)
    return merged
