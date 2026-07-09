"""
Background job: describe memes using OpenRouter FREE vision models only.

Populates meme.ocr_result JSONB with:
- description: what the meme shows, the joke
- text: raw OCR text extracted from the image
- language: detected language (ISO 639-1)
- described_by: model used
- calculated_at: timestamp (use this field, NOT meme.created_at, for monitoring)

Processes recent user uploads first, then most popular memes (by nlikes DESC).
Runs every 15 min via Prefect cron, 9 memes per scheduled batch.

IMPORTANT — OpenRouter free tier rules:
- Need $10+ lifetime purchases for 1,000 free-model req/day (otherwise 50/day).
- NEVER add paid models — this client refuses any model not ending in ":free".
- Current balance must stay >= $0. Monitor at https://openrouter.ai/settings/credits
- Free model rate limit: 20 rpm across all free models.
- Local safety budget: 900 OpenRouter attempts/day to leave room for uploads/retries.
- Free-model 429s/timeouts are normal. Cool down the model and retry in later runs.
- See specs/describe-memes.md for full constraints.

Circuit breaker: auto-paused after 3 failures in 1 hour.
  Resume: prefect deployment resume "describe-memes-flow/describe-memes"
"""

import asyncio
import base64
import time

from prefect import flow, get_run_logger

from src.config import settings
from src.flows.events import safe_emit
from src.flows.hooks import notify_telegram_on_failure
from src.flows.storage.describe_memes_repository import (
    get_memes_to_describe,
    increment_describe_failures,
    save_meme_description,
)
from src.flows.storage.openrouter_vision import (
    ALL_FAILED,
    DAILY_BUDGET_EXHAUSTED,
    QUOTA_EXHAUSTED,
    RATE_LIMITED,
    VISION_MODELS,
    call_openrouter_vision,
    check_openrouter_key_health,
)
from src.storage.deduplication import deduplicate_described_meme
from src.storage.upload import download_meme_content_from_tg

__all__ = ["VISION_MODELS", "describe_memes_flow", "describe_single_meme"]


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
        await increment_describe_failures(meme_id, existing_ocr, str(e))
        return "failed"

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    # Call vision model
    try:
        result = await call_openrouter_vision(image_b64, log, deadline=deadline)
    except Exception as e:
        log.warning("Meme %s: OpenRouter error: %s", meme_id, e)
        await increment_describe_failures(meme_id, existing_ocr, str(e))
        return "failed"

    if result is None:
        await increment_describe_failures(meme_id, existing_ocr, "no result")
        return "failed"

    if result.get(RATE_LIMITED):
        retry_after = result.get("__retry_after")
        if retry_after is not None:
            return ("rate_limited", retry_after)
        return "rate_limited"

    if result.get(QUOTA_EXHAUSTED):
        return "quota_exhausted"

    if result.get(DAILY_BUDGET_EXHAUSTED):
        return "daily_budget_exhausted"

    if result.get(ALL_FAILED):
        await increment_describe_failures(meme_id, existing_ocr, "all models failed")
        return "failed"

    merged = await save_meme_description(meme_id, existing_ocr, result)
    dedup_result = await deduplicate_described_meme(
        meme_id,
        merged.get("text", ""),
        status=meme_row.get("status"),
    )
    if dedup_result.duplicate_found:
        log.info(
            "Meme %s resolved as OCR duplicate of %s after describe: %s",
            meme_id,
            dedup_result.duplicate_of,
            dedup_result.resolution,
        )
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

    if not await check_openrouter_key_health(log):
        log.warning("OpenRouter key is not usable. Skipping Describe Memes batch.")
        return

    memes = await get_memes_to_describe(limit=batch_size)
    log.info("Found %d memes to describe.", len(memes))

    if not memes:
        return

    ok = 0
    failed = 0
    consecutive_fails = 0
    # Hard deadline: stop 120s before the 900s flow timeout.
    # Anchored to flow_start so pre-batch query time is accounted for.
    batch_deadline = flow_start + 780
    # Per-meme timeout: no single meme should block the batch
    per_meme_timeout = 120
    # Minimum interval between request starts to stay under 20 rpm rate limit.
    # 10s = 6 rpm effective: slower, but friendlier to free model capacity.
    min_request_interval = 10.0

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
            await increment_describe_failures(
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
            log.info("Described meme %d (%d/%d)", meme_row["id"], i + 1, len(memes))
        elif status == "rate_limited":
            log.info(
                "All currently usable free models are rate-limited/cooling down "
                "at meme %d (%d/%d). Stopping batch; next scheduled run will retry "
                "after cooldowns (next retry in %ss).",
                meme_row["id"],
                i + 1,
                len(memes),
                int(retry_after) if retry_after is not None else "unknown",
            )
            break
        elif status in {"quota_exhausted", "daily_budget_exhausted"}:
            if status == "daily_budget_exhausted":
                log.warning(
                    "OpenRouter daily safety budget exhausted at meme %d (%d/%d). "
                    "Stopping batch before the 1,000/day free-model cap.",
                    meme_row["id"],
                    i + 1,
                    len(memes),
                )
                break
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
