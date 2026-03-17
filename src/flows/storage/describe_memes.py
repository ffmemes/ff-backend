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
import logging
from datetime import datetime, timezone

import httpx
from prefect import flow, get_run_logger

from src.config import settings
from src.database import fetch_all, fetch_one, meme
from src.flows.hooks import notify_telegram_on_failure
from src.storage.upload import download_meme_content_from_tg

logger = logging.getLogger(__name__)

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


async def get_memes_to_describe(limit: int = 30) -> list[dict]:
    """Get image memes without descriptions, ordered by popularity."""
    from sqlalchemy import text

    query = text("""
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
        ORDER BY COALESCE(MS.nmemes_sent, 0) DESC, M.id DESC
        LIMIT :limit
    """).bindparams(limit=limit)

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


async def call_openrouter_vision(image_b64: str) -> dict | None:
    """Call OpenRouter vision model with fallback chain on 429 errors."""
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

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
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{OPENROUTER_BASE_URL}/chat/completions",
                    headers=headers,
                    json=payload,
                )

            if response.status_code == 429:
                logger.info("Model %s rate-limited, trying next...", model_id)
                await asyncio.sleep(2)
                continue

            response.raise_for_status()

            # Parse response body (may have leading whitespace from streaming)
            body = response.text.strip()
            json_start = body.find("{")
            if json_start < 0:
                logger.warning("Model %s returned no JSON: %s", model_id, body[:100])
                continue
            data = json.loads(body[json_start:])

            if "choices" not in data:
                logger.warning("Model %s returned no choices: %s", model_id, str(data)[:200])
                continue

            content = data["choices"][0]["message"]["content"]
            if not content:
                logger.warning("Model %s returned empty content", model_id)
                continue
            result = _parse_vision_response(content)

            # Validate expected keys
            if "description" not in result and "ocr_text" not in result:
                logger.warning("Model %s returned unexpected JSON: %s", model_id, str(result)[:200])
                continue

            result["__model"] = model_id
            return result

        except json.JSONDecodeError as e:
            logger.warning("Model %s returned invalid JSON: %s", model_id, e)
            continue
        except httpx.HTTPStatusError as e:
            logger.warning("Model %s HTTP error: %s", model_id, e)
            continue
        except Exception as e:
            logger.warning("Model %s unexpected error: %s", model_id, e)
            continue

    # All models exhausted
    return {"__rate_limited": True}


async def describe_single_meme(meme_row: dict) -> bool:
    """Download, analyze, and update a single meme. Returns True on success."""
    meme_id = meme_row["id"]
    file_id = meme_row["telegram_file_id"]
    existing_ocr = meme_row["ocr_result"] or {}

    # Download image from Telegram
    try:
        image_bytes = await download_meme_content_from_tg(file_id)
    except Exception as e:
        logger.warning("Failed to download meme %s from TG: %s", meme_id, e)
        return False

    # Base64 encode
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    # Call vision model
    try:
        result = await call_openrouter_vision(image_b64)
    except json.JSONDecodeError as e:
        logger.warning("Meme %s: model returned invalid JSON: %s", meme_id, e)
        return False
    except httpx.HTTPStatusError as e:
        logger.warning("Meme %s: OpenRouter API error: %s", meme_id, e)
        return False
    except Exception as e:
        logger.warning("Meme %s: unexpected error calling OpenRouter: %s", meme_id, e)
        return False

    if result is None:
        return False

    if result.get("__rate_limited"):
        return False  # caller should stop the batch

    # Merge with existing ocr_result, matching OcrResult schema:
    # {"text": "...", "model": "...", "raw_result": {...}, "calculated_at": "..."}
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

    # Only overwrite "text" if there was no existing OCR text.
    # "text" is the canonical key used by all SQL queries and the GIN index.
    if not existing_ocr.get("text"):
        merged["text"] = ocr_text

    # Update meme
    update_kwargs = {"ocr_result": merged}

    # Update language_code if we detected one and meme had none
    if language and not meme_row.get("language_code"):
        update_kwargs["language_code"] = language

    update_query = meme.update().where(meme.c.id == meme_id).values(**update_kwargs).returning(meme)
    await fetch_one(update_query)
    return True


@flow(
    name="Describe Memes (OpenRouter Vision)",
    description="Analyze meme images with free vision models.",
    version="0.1.0",
    log_prints=True,
    retries=1,
    retry_delay_seconds=60,
    timeout_seconds=900,
    on_failure=[notify_telegram_on_failure],
)
async def describe_memes_flow(batch_size: int = 30) -> None:
    log = get_run_logger()

    if not settings.OPENROUTER_API_KEY:
        log.warning("OPENROUTER_API_KEY not set. Skipping meme description flow.")
        return

    memes = await get_memes_to_describe(limit=batch_size)
    log.info("Found %d memes to describe.", len(memes))

    if not memes:
        return

    success_count = 0
    error_count = 0

    for i, meme_row in enumerate(memes):
        ok = await describe_single_meme(meme_row)

        if ok:
            success_count += 1
            log.info(
                "Described meme %d (%d/%d)",
                meme_row["id"],
                i + 1,
                len(memes),
            )
        else:
            error_count += 1
            # Check if rate limited — stop the entire batch
            log.warning("Failed to describe meme %d (%d/%d)", meme_row["id"], i + 1, len(memes))

        # Rate limit: ~15 req/min = 4 sec between requests
        if i < len(memes) - 1:
            await asyncio.sleep(4)

    log.info(
        "Batch complete: %d described, %d errors, %d total.",
        success_count,
        error_count,
        len(memes),
    )
