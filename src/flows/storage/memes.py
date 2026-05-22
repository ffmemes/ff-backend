from typing import Any

from prefect import flow, get_run_logger

from src.flows.events import safe_emit
from src.flows.hooks import notify_telegram_on_failure
from src.storage import ads
from src.storage.constants import MemeStatus, MemeType
from src.storage.deduplication import (
    deduplicate_pending_meme,
    sweep_file_id_duplicates,
)
from src.storage.etl import (
    etl_memes_from_raw_telegram_posts,
    etl_memes_from_raw_vk_posts,
)
from src.storage.service import (
    get_pending_memes,
    get_unloaded_tg_memes,
    get_unloaded_vk_memes,
    update_meme,
    update_meme_status_of_ready_memes,
)
from src.storage.upload import (
    download_meme_content_file,
    upload_meme_content_to_tg,
)
from src.storage.watermark import add_watermark


async def analyse_meme_caption(meme: dict[str, Any]) -> None:
    if meme["caption"] is None:
        return

    if ads.text_is_adverisement(meme["caption"]):
        await update_meme(meme["id"], status=MemeStatus.AD)
        return

    new_caption = ads.filter_caption(meme["caption"])
    if new_caption != meme["caption"]:
        await update_meme(meme["id"], caption=new_caption)

    if meme["language_code"] == "en":
        _ru_chars = set("йцукенгшщзхъёфывапролджэячсмитьбю")
        if len(set(meme["caption"]) & _ru_chars) > 0:
            await update_meme(meme["id"], language_code="ru")
            return


async def add_watermark_to_meme_content(meme_content: bytes, meme_type: MemeType) -> bytes | None:
    if meme_type == MemeType.IMAGE:
        # we can add watermark only to photos right now
        watermarked_content = add_watermark(meme_content)
        if watermarked_content is None:
            return None
        return watermarked_content.getvalue()
    return meme_content


async def upload_meme_to_telegram(
    meme: dict[str, Any],
) -> dict[str, Any] | None:
    logger = get_run_logger()

    logger.info(f"Downloading meme {meme['id']} content file.")
    meme_original_content = await download_meme_content_file(meme["content_url"])
    if meme_original_content is None:
        logger.warning(f"Can't download {meme['id']}/{meme['type']} content")
        await update_meme(meme["id"], status=MemeStatus.BROKEN_CONTENT_LINK)
        return None

    watermarked_meme_content = await add_watermark_to_meme_content(
        meme_original_content, meme["type"]
    )
    if watermarked_meme_content is None:
        logger.warning(f"Can't add watermark to {meme['id']}/{meme['type']} content")
        return None

    meme_result = await upload_meme_content_to_tg(meme, watermarked_meme_content)
    if meme_result is None:
        logger.warning(f"Can't upload {meme['id']}/{meme['type']} content to Telegram")
        return None

    return meme_result


async def _process_unloaded_memes(
    unloaded_memes: list[dict[str, Any]],
    source_name: str,
) -> None:
    """Shared pipeline: download, watermark, upload to TG storage.

    Resilient per-meme: a single download/upload failure doesn't kill the batch.
    Stops early if too many consecutive failures (likely systemic issue).
    """
    logger = get_run_logger()
    total = len(unloaded_memes)
    logger.info(f"Processing {total} unloaded {source_name} memes.")

    ok_count = 0
    fail_count = 0
    consecutive_fails = 0

    for i, unloaded_meme in enumerate(unloaded_memes):
        try:
            meme = await upload_meme_to_telegram(unloaded_meme)
        except Exception as e:
            logger.warning(f"Meme {unloaded_meme['id']}: upload error: {e}")
            fail_count += 1
            consecutive_fails += 1
            if consecutive_fails >= 5:
                logger.error(
                    f"5 consecutive failures — stopping batch. "
                    f"Processed {i + 1}/{total}, {ok_count} ok, {fail_count} failed."
                )
                break
            continue

        if not meme:
            fail_count += 1
            consecutive_fails += 1
            if consecutive_fails >= 5:
                logger.error(
                    f"5 consecutive failures — stopping batch. "
                    f"Processed {i + 1}/{total}, {ok_count} ok, {fail_count} failed."
                )
                break
            continue

        ok_count += 1
        consecutive_fails = 0

    logger.info(f"Batch done: {ok_count} uploaded, {fail_count} failed out of {total}.")


@flow(
    name="Memes from Telegram Pipeline",
    description="Process raw memes parsed from Telegram",
    version="0.3.0",
    log_prints=True,
    retries=1,
    retry_delay_seconds=60,
    timeout_seconds=1800,
    on_failure=[notify_telegram_on_failure],
)
async def tg_meme_pipeline() -> None:
    logger = get_run_logger()
    logger.info("ETLing memes from 'meme_raw_telegram' table.")
    await etl_memes_from_raw_telegram_posts()

    unloaded_memes = await get_unloaded_tg_memes(limit=100)
    await _process_unloaded_memes(unloaded_memes, "Telegram")

    safe_emit("ff.pipeline.telegram.completed", "ff.pipeline.telegram")


async def process_cached_telegram_source(meme_source_id: int, limit: int = 100) -> None:
    """Process cached raw Telegram posts for one just-enabled source."""
    await etl_memes_from_raw_telegram_posts([meme_source_id], fresh_only=False)
    unloaded_memes = await get_unloaded_tg_memes(
        limit=limit,
        meme_source_ids=[meme_source_id],
        fresh_only=False,
    )
    await _process_unloaded_memes(unloaded_memes, "prepared Telegram source")
    # Run the same finalization path as scheduled pipelines so dedup logic
    # (file_id exact + OCR fuzzy) is applied before memes become publishable.
    await final_meme_pipeline()


@flow(
    name="Memes from VK Pipeline",
    description="Process raw memes parsed from VK",
    version="0.3.0",
    retries=1,
    retry_delay_seconds=60,
    timeout_seconds=1800,
    on_failure=[notify_telegram_on_failure],
)
async def vk_meme_pipeline() -> None:
    logger = get_run_logger()
    logger.info("ETLing memes from 'meme_raw_vk' table.")
    await etl_memes_from_raw_vk_posts()

    unloaded_memes = await get_unloaded_vk_memes(limit=100)
    await _process_unloaded_memes(unloaded_memes, "VK")

    safe_emit("ff.pipeline.vk.completed", "ff.pipeline.vk")


@flow(
    name="Final Memes Pipeline",
    retries=1,
    retry_delay_seconds=30,
    timeout_seconds=1800,
    on_failure=[notify_telegram_on_failure],
)
async def final_meme_pipeline() -> None:
    logger = get_run_logger()

    memes = await get_pending_memes()
    logger.info(f"Final meme pipeline has {len(memes)} pending memes.")

    processed_meme_ids = []
    for meme in memes:
        processed_meme_ids.append(meme["id"])
        await analyse_meme_caption(meme)

        result = await deduplicate_pending_meme(meme)
        if result.duplicate_found:
            logger.info(
                "Meme %s resolved as %s duplicate of %s before ok promotion.",
                result.meme_id,
                result.reason,
                result.duplicate_of,
            )

    promoted_memes = await update_meme_status_of_ready_memes(processed_meme_ids)
    file_id_duplicates = await sweep_file_id_duplicates()
    if file_id_duplicates["resolved"]:
        logger.info("Resolved file_id duplicates: %s", file_id_duplicates)

    safe_emit(
        "ff.pipeline.final.completed",
        "ff.pipeline.final",
        {
            "memes_processed": len(memes),
            "memes_promoted": len(promoted_memes),
            "file_id_duplicates_resolved": file_id_duplicates["resolved"],
        },
    )
