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


def _text_or_empty(value: Any) -> str:
    return value if isinstance(value, str) else ""


async def get_memes_to_describe(limit: int = 30) -> list[dict[str, Any]]:
    """Get image memes without descriptions.

    Priority order:
    1. Recently uploaded memes (last 24h) — enables dedup for user uploads
    2. Most liked memes — improves Wrapped coverage

    Skips memes that have failed 3+ times (tracked in ocr_result.describe_failures).
    """
    query = text(
        """
        SELECT
            M.id,
            M.telegram_file_id,
            M.ocr_result,
            M.status,
            M.language_code
        FROM meme M
        LEFT JOIN meme_stats MS ON MS.meme_id = M.id
        LEFT JOIN meme_source SRC ON SRC.id = M.meme_source_id
        WHERE M.type = 'image'
            AND M.status = 'ok'
            AND M.telegram_file_id IS NOT NULL
            AND (
                M.ocr_result IS NULL
                OR M.ocr_result->>'description' IS NULL
            )
            AND COALESCE((M.ocr_result->>'describe_failures')::int, 0) < 3
        ORDER BY
            CASE WHEN SRC.type = 'user upload'
                 AND M.created_at > now() - interval '24 hours'
                 THEN 0 ELSE 1 END,
            COALESCE(MS.nlikes, 0) DESC,
            M.id DESC
        LIMIT :limit
    """
    ).bindparams(limit=limit)

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
