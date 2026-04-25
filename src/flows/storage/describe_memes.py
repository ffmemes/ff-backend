"""
Background job: describe memes using OpenRouter FREE vision models only.

Populates meme.ocr_result JSONB with:
- description: what the meme shows, the joke
- text: raw OCR text extracted from the image
- language: detected language (ISO 639-1)
- described_by: model used
- calculated_at: timestamp (use this field, NOT meme.created_at, for monitoring)

Processes most popular memes first (by nlikes DESC).
Runs every 60 min via Prefect cron, ~20 memes per batch.

IMPORTANT — OpenRouter free tier rules:
- Need $10+ lifetime purchases for 1,000 req/day (otherwise only 50/day).
- NEVER add paid models — if balance drops below $0, ALL models (incl free) get 402.
- Current balance must stay >= $0. Monitor at https://openrouter.ai/settings/credits
- Free model rate limit: 20 rpm across all free models.
- See specs/describe-memes.md for full constraints.

Circuit breaker: auto-paused after 3 failures in 1 hour.
  Resume: prefect deployment resume "describe-memes-flow/describe-memes"
"""

import asyncio
import base64
import json
import re
import time
from datetime import datetime, timezone

import httpx
from prefect import flow, get_run_logger

from src.config import settings
from src.database import execute, fetch_all, fetch_one, meme
from src.flows.events import safe_emit
from src.flows.hooks import notify_telegram_on_failure
from src.storage.upload import download_meme_content_from_tg

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# FREE models only. Never add paid models here — spending balance below $0
# blocks ALL models (even free ones) with HTTP 402. Free tier requires $10+
# lifetime purchases for 1,000 req/day (vs 50/day without).
# See specs/describe-memes.md for full OpenRouter constraints.
#
# Verified available on OpenRouter API as of 2026-04-20.
# Ordered by preference. Falls back to next model on 429/403/error.
VISION_MODELS = [
    "google/gemma-4-31b-it:free",  # 262k context, primary
    "google/gemma-4-26b-a4b-it:free",  # 262k context, MoE variant
    "google/gemma-3-27b-it:free",  # 131k context, re-listed on OpenRouter ~2026-04-20
    "google/gemma-3-12b-it:free",  # 32k context, re-listed on OpenRouter ~2026-04-20
    # nvidia/nemotron-nano-12b-v2-vl:free removed — returns 504s and invalid
    # JSON/empty content (see specs/describe-memes.md).
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
QUOTA_EXHAUSTED = "__quota_exhausted"


async def get_memes_to_describe(limit: int = 30) -> list[dict]:
    """Get image memes without descriptions.

    Priority order:
    1. Recently uploaded memes (last 24h) — enables dedup for user uploads
    2. Most liked memes — improves Wrapped coverage

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


def _parse_vision_response(raw_content: str) -> dict:
    """Parse JSON from model response, stripping markdown fences if present.

    Falls back to escape-fixing and regex extraction to handle common LLM JSON issues
    (invalid escape sequences, unterminated strings from lower-quality models).
    """
    content = raw_content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    if content.startswith("json"):
        content = content[4:].strip()

    # 1. Standard parse
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 2. Fix invalid escape sequences (e.g. \' or \k not valid in JSON)
    try:
        fixed = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", content)
        return json.loads(fixed)
    except json.JSONDecodeError, Exception:
        pass

    # 3. Regex extraction — last resort for severely malformed output
    result = {}
    for key in ("ocr_text", "description", "language"):
        match = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"', content, re.DOTALL)
        if match:
            try:
                result[key] = json.loads(f'"{match.group(1)}"')
            except json.JSONDecodeError:
                result[key] = match.group(1)
    if result:
        return result

    raise json.JSONDecodeError("Could not parse model response", content, 0)


def _parse_retry_after(response: httpx.Response) -> float | None:
    """Extract retry delay from Retry-After header or response body."""
    header = response.headers.get("retry-after") or response.headers.get("x-ratelimit-reset")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    try:
        body = response.json()
        if "error" in body and "metadata" in body["error"]:
            reset = body["error"]["metadata"].get("ratelimit_reset")
            if reset:
                return float(reset)
    except Exception:
        pass
    return None


async def call_openrouter_vision(image_b64: str, log, *, deadline: float | None = None) -> dict:
    """Call OpenRouter vision model with fallback chain.

    Args:
        deadline: monotonic timestamp after which we stop trying models.

    Returns:
        dict with result on success, or {RATE_LIMITED: True} / {ALL_FAILED: True}
    """
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        for model_id in VISION_MODELS:
            # Stop trying more models if we're running out of time
            if deadline is not None and time.monotonic() > deadline - 35:
                log.warning("Skipping remaining models — approaching deadline")
                break

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
                response = await client.post(
                    f"{OPENROUTER_BASE_URL}/chat/completions",
                    headers=headers,
                    json=payload,
                )

                if response.status_code == 402:
                    log.warning(
                        "OpenRouter quota exhausted (HTTP 402). "
                        "Balance likely below $0 — all models blocked. "
                        "Check https://openrouter.ai/settings/credits"
                    )
                    return {QUOTA_EXHAUSTED: True}

                if response.status_code == 429:
                    retry_after = _parse_retry_after(response)
                    log.info(
                        "Rate-limited (429) on %s (retry-after: %ss)",
                        model_id,
                        retry_after or "unknown",
                    )
                    return {RATE_LIMITED: True, "__retry_after": retry_after}

                if response.status_code == 403:
                    log.warning("Model %s HTTP 403 (access denied), trying next...", model_id)
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

    # All models exhausted (403, timeout, bad response — not 429, which returns early)
    return {ALL_FAILED: True}


async def _increment_describe_failures(meme_id: int, existing_ocr: dict, reason: str):
    """Track describe failures in ocr_result so permanently broken memes get skipped."""
    failures = int(existing_ocr.get("describe_failures", 0)) + 1
    merged = {**existing_ocr, "describe_failures": failures, "last_failure_reason": reason}
    update_query = meme.update().where(meme.c.id == meme_id).values(ocr_result=merged)
    await execute(update_query)


async def describe_single_meme(meme_row: dict, log, *, deadline: float | None = None) -> str:
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
        result = await call_openrouter_vision(image_b64, log, deadline=deadline)
    except Exception as e:
        log.warning("Meme %s: OpenRouter error: %s", meme_id, e)
        await _increment_describe_failures(meme_id, existing_ocr, str(e))
        return "failed"

    if result is None:
        await _increment_describe_failures(meme_id, existing_ocr, "no result")
        return "failed"

    if result.get(RATE_LIMITED):
        retry_after = result.get("__retry_after")
        if retry_after is not None:
            return ("rate_limited", retry_after)
        return "rate_limited"

    if result.get(QUOTA_EXHAUSTED):
        return "quota_exhausted"

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
async def describe_memes_flow(batch_size: int = 20) -> None:
    log = get_run_logger()

    # Anchor to flow start, not batch start — the Prefect flow timeout (900s)
    # ticks from here, so our deadline must be relative to this moment.
    flow_start = time.monotonic()

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
    rate_limit_waits = 0
    max_rate_limit_waits = 3
    # Hard deadline: stop 120s before the 900s flow timeout.
    # Anchored to flow_start so pre-batch query time is accounted for.
    batch_deadline = flow_start + 780
    # Per-meme timeout: no single meme should block the batch
    per_meme_timeout = 120
    # Minimum interval between request starts to stay under 20 rpm rate limit.
    # 4.0s = 15 rpm effective, well under the 20 rpm cap with margin for bursts.
    min_request_interval = 4.0

    i = 0
    while i < len(memes):
        meme_row = memes[i]
        remaining = batch_deadline - time.monotonic()
        if remaining < per_meme_timeout + 15:
            log.warning(
                "Approaching timeout (%.0fs remaining, need %ds). Stopping batch at %d/%d.",
                remaining,
                per_meme_timeout + 15,
                i,
                len(memes),
            )
            break

        request_start = time.monotonic()
        # Cap the per-meme timeout to actual remaining time minus a safety buffer
        effective_timeout = min(per_meme_timeout, remaining - 15)
        meme_deadline = min(time.monotonic() + effective_timeout, batch_deadline - 10)

        try:
            status = await asyncio.wait_for(
                describe_single_meme(meme_row, log, deadline=meme_deadline),
                timeout=effective_timeout,
            )
        except asyncio.TimeoutError:
            log.warning(
                "Meme %d timed out after %ds (%d/%d)",
                meme_row["id"],
                effective_timeout,
                i + 1,
                len(memes),
            )
            await _increment_describe_failures(
                meme_row["id"],
                meme_row["ocr_result"] or {},
                f"per-meme timeout ({effective_timeout:.0f}s)",
            )
            status = "failed"

        retry_after = None
        if isinstance(status, tuple):
            status, retry_after = status

        if status == "ok":
            ok += 1
            consecutive_fails = 0
            rate_limit_waits = 0
            log.info("Described meme %d (%d/%d)", meme_row["id"], i + 1, len(memes))
        elif status == "rate_limited":
            if rate_limit_waits >= max_rate_limit_waits:
                log.warning(
                    "Rate-limited %d times at meme %d (%d/%d). "
                    "Likely daily quota exhausted — stopping batch.",
                    rate_limit_waits + 1,
                    meme_row["id"],
                    i + 1,
                    len(memes),
                )
                break
            wait_secs = min(retry_after or 65.0, 65.0)
            if batch_deadline - time.monotonic() < wait_secs + per_meme_timeout + 15:
                log.warning(
                    "Rate-limited but not enough time to wait %.0fs — stopping batch.",
                    wait_secs,
                )
                break
            rate_limit_waits += 1
            log.info(
                "Rate-limited at meme %d (%d/%d). Waiting %.0fs before retry (%d/%d waits).",
                meme_row["id"],
                i + 1,
                len(memes),
                wait_secs,
                rate_limit_waits,
                max_rate_limit_waits,
            )
            await asyncio.sleep(wait_secs)
            continue
        elif status == "quota_exhausted":
            log.warning(
                "OpenRouter quota exhausted at meme %d (%d/%d). "
                "Stopping batch — balance likely below $0. "
                "Top up at https://openrouter.ai/settings/credits",
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

        i += 1
        if i < len(memes):
            request_elapsed = time.monotonic() - request_start
            sleep_needed = max(0, min_request_interval - request_elapsed)
            if sleep_needed > 0:
                await asyncio.sleep(sleep_needed)

    log.info("Batch: %d described, %d failed out of %d.", ok, failed, len(memes))

    safe_emit(
        "ff.describe_memes.completed",
        "ff.describe_memes",
        {"described": ok, "failed": failed},
    )
