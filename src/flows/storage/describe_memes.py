"""
Background job: describe memes using OpenRouter free vision models.

Populates meme.ocr_result JSONB with:
- description: what the meme shows, the joke
- text: raw OCR text extracted from the image
- language: detected language (ISO 639-1)
- described_by: model used
- described_at: timestamp

Processes most popular memes first (by nmemes_sent).
Runs every 30 min via Prefect cron, ~30 memes per batch.
"""

import asyncio
import base64
import json
from datetime import datetime, timezone

import httpx
from prefect import flow, get_run_logger

from src.config import settings
from src.database import execute, fetch_all, fetch_one, meme
from src.flows.events import safe_emit
from src.flows.hooks import notify_telegram_on_failure
from src.storage.upload import download_meme_content_from_tg

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Ordered by preference. Falls back to next model on 429/error.
VISION_MODELS = [
    "google/gemma-3-27b-it:free",  # best quality, 140+ languages
    "google/gemma-3-12b-it:free",  # good fallback, smaller
    "nvidia/nemotron-nano-12b-v2-vl:free",  # best OCR, fast
    "mistralai/mistral-small-3.1-24b-instruct:free",  # good multilingual
]

DESCRIBE_PROMPT = (
    "You are analyzing a meme image. Extract the following:\n\n"
    "1. OCR_TEXT: ALL text visible in the image, exactly as written. "
    "Preserve original language and line breaks. "
    "If no text, return empty string.\n\n"
    "2. DESCRIPTION: Describe the meme in 1-3 sentences in English. "
    "What's happening visually? What's the joke? "
    "Be specific (panels, characters, reactions, meme format).\n\n"
    "3. LANGUAGE: Primary language of the meme text as ISO 639-1 code "
    '(e.g. "ru", "en"). If no text, return "en". '
    "If mixed, return dominant language.\n\n"
    "Respond with ONLY valid JSON, no markdown fences:\n"
    '{"ocr_text": "...", "description": "...", "language": "..."}'
)

# Sentinel return values from call_openrouter_vision
RATE_LIMITED = "__rate_limited"
ALL_FAILED = "__all_failed"


async def get_memes_to_describe(limit: int = 30) -> list[dict]:
    """Get image memes without descriptions, ordered by likes (most liked first).

    Prioritizes memes that active users have liked — directly improves Wrapped coverage.
    Skips memes that have failed 3+ times (tracked in ocr_result.describe_failures).
    """
    from sqlalchemy import text

    query = text(
        """
        SELECT
            M.id,
            M.telegram_file_id,
            M.ocr_result,
            M.language_code
        FROM meme M
        LEFT JOIN meme_stats MS ON MS.meme_id = M.id
        WHERE M.type = 'image'
            AND M.status = 'ok'
            AND M.telegram_file_id IS NOT NULL
            AND (
                M.ocr_result IS NULL
                OR M.ocr_result->>'description' IS NULL
            )
            AND COALESCE((M.ocr_result->>'describe_failures')::int, 0) < 3
        ORDER BY COALESCE(MS.nlikes, 0) DESC, M.id DESC
        LIMIT :limit
    """
    ).bindparams(limit=limit)

    return await fetch_all(query)


def _parse_vision_response(raw_content: str) -> dict:
    """Parse JSON from model response, stripping markdown fences if present."""
    content = raw_content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    if content.startswith("json"):
        content = content[4:].strip()

    return json.loads(content)


async def call_openrouter_vision(image_b64: str, log) -> dict:
    """Call OpenRouter vision model with fallback chain.

    Returns:
        dict with result on success, or {RATE_LIMITED: True} / {ALL_FAILED: True}
    """
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    rate_limited_count = 0

    for model_id in VISION_MODELS:
        payload = {
            "model": model_id,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": DESCRIBE_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}",
                            },
                        },
                    ],
                }
            ],
            "max_tokens": 500,
            "temperature": 0.2,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{OPENROUTER_BASE_URL}/chat/completions",
                    headers=headers,
                    json=payload,
                )

            if response.status_code == 429:
                log.debug("Model %s rate-limited, trying next...", model_id)
                rate_limited_count += 1
                await asyncio.sleep(1)
                continue

            response.raise_for_status()

            body = response.text.strip()
            json_start = body.find("{")
            if json_start < 0:
                log.warning("Model %s returned no JSON: %s", model_id, body[:100])
                continue
            data = json.loads(body[json_start:])

            if "choices" not in data:
                log.warning("Model %s no choices: %s", model_id, str(data)[:200])
                continue

            content = data["choices"][0]["message"]["content"]
            if not content:
                log.warning("Model %s empty content", model_id)
                continue
            result = _parse_vision_response(content)

            if "description" not in result and "ocr_text" not in result:
                log.warning("Model %s bad JSON: %s", model_id, str(result)[:200])
                continue

            result["__model"] = model_id
            return result

        except json.JSONDecodeError as e:
            log.warning("Model %s invalid JSON: %s", model_id, e)
            continue
        except httpx.HTTPStatusError as e:
            log.warning("Model %s HTTP %s", model_id, e.response.status_code)
            continue
        except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:
            log.warning("Model %s timeout: %s", model_id, type(e).__name__)
            continue
        except Exception as e:
            log.warning("Model %s error: %s", model_id, e)
            continue

    # All models exhausted
    if rate_limited_count == len(VISION_MODELS):
        return {RATE_LIMITED: True}
    return {ALL_FAILED: True}


async def _increment_describe_failures(meme_id: int, existing_ocr: dict, reason: str):
    """Track describe failures in ocr_result so permanently broken memes get skipped."""
    failures = int(existing_ocr.get("describe_failures", 0)) + 1
    merged = {**existing_ocr, "describe_failures": failures, "last_failure_reason": reason}
    update_query = meme.update().where(meme.c.id == meme_id).values(ocr_result=merged)
    await execute(update_query)


async def describe_single_meme(meme_row: dict, log) -> str:
    """Download, analyze, and update a single meme.

    Returns: "ok", "rate_limited", "failed"
    """
    meme_id = meme_row["id"]
    file_id = meme_row["telegram_file_id"]
    existing_ocr = meme_row["ocr_result"] or {}

    # Download image from Telegram
    try:
        image_bytes = await download_meme_content_from_tg(file_id)
    except Exception as e:
        log.warning("Meme %s: download failed: %s", meme_id, e)
        await _increment_describe_failures(meme_id, existing_ocr, str(e))
        return "failed"

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    # Call vision model
    try:
        result = await call_openrouter_vision(image_b64, log)
    except Exception as e:
        log.warning("Meme %s: OpenRouter error: %s", meme_id, e)
        await _increment_describe_failures(meme_id, existing_ocr, str(e))
        return "failed"

    if result is None:
        await _increment_describe_failures(meme_id, existing_ocr, "no result")
        return "failed"

    if result.get(RATE_LIMITED):
        return "rate_limited"

    if result.get(ALL_FAILED):
        await _increment_describe_failures(meme_id, existing_ocr, "all models failed")
        return "failed"

    # Merge with existing ocr_result
    ocr_text = result.get("ocr_text", "")
    description = result.get("description", "")
    language = result.get("language", "")
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

    update_kwargs = {"ocr_result": merged}

    # Only update language_code if the detected language is one we already use
    # This ensures inner joins with user_language work correctly
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
    if language and language.lower() in KNOWN_LANGUAGES:
        update_kwargs["language_code"] = language.lower()

    update_query = meme.update().where(meme.c.id == meme_id).values(**update_kwargs).returning(meme)
    await fetch_one(update_query)
    return "ok"


@flow(
    name="Describe Memes (OpenRouter Vision)",
    description="Analyze meme images with free vision models.",
    version="0.2.0",
    log_prints=True,
    retries=0,
    timeout_seconds=900,
    on_failure=[notify_telegram_on_failure],
)
async def describe_memes_flow(batch_size: int = 30) -> None:
    log = get_run_logger()

    if not settings.OPENROUTER_API_KEY:
        log.warning("OPENROUTER_API_KEY not set. Skipping.")
        return

    memes = await get_memes_to_describe(limit=batch_size)
    log.info("Found %d memes to describe.", len(memes))

    if not memes:
        return

    ok = 0
    failed = 0
    consecutive_fails = 0

    for i, meme_row in enumerate(memes):
        status = await describe_single_meme(meme_row, log)

        if status == "ok":
            ok += 1
            consecutive_fails = 0
            log.info("Described meme %d (%d/%d)", meme_row["id"], i + 1, len(memes))
        elif status == "rate_limited":
            log.warning(
                "All models rate-limited at meme %d (%d/%d). " "Stopping batch — quota exhausted.",
                meme_row["id"],
                i + 1,
                len(memes),
            )
            break
        else:
            failed += 1
            consecutive_fails += 1
            log.warning(
                "Failed meme %d (%d/%d, %d consecutive)",
                meme_row["id"],
                i + 1,
                len(memes),
                consecutive_fails,
            )
            if consecutive_fails >= 3:
                log.warning("3 consecutive failures — stopping batch.")
                break

        if i < len(memes) - 1:
            await asyncio.sleep(4)

    log.info("Batch: %d described, %d failed out of %d.", ok, failed, len(memes))

    safe_emit(
        "ff.describe_memes.completed",
        "ff.describe_memes",
        {"described": ok, "failed": failed},
    )
