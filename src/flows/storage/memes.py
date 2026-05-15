from typing import Any

from prefect import flow, get_run_logger

from src.flows.events import safe_emit
from src.flows.hooks import notify_telegram_on_failure
from src.storage import ads
from src.storage.constants import MemeStatus, MemeType
from src.storage.etl import (
    etl_memes_from_raw_telegram_posts,
    etl_memes_from_raw_vk_posts,
)
from src.storage.service import (
    find_meme_duplicate,
    find_meme_duplicate_by_file_id,
    get_pending_memes,
    get_unloaded_tg_memes,
    get_unloaded_vk_memes,
    resolve_meme_duplicate,
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


async def add_watermark_to_meme_content(meme_content: bytes, meme_type: MemeType) -> bytes:
    if meme_type == MemeType.IMAGE:
        # we can add watermark only to photos right now
        return add_watermark(meme_content)
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

    for meme in memes:
        await analyse_meme_caption(meme)

        # exact file_id dedup: catches cross-source reposts of identical files
        if meme["telegram_file_id"]:
            dup_id = await find_meme_duplicate_by_file_id(meme["id"], meme["telegram_file_id"])
            if dup_id:
                await resolve_meme_duplicate(meme["id"], dup_id)
                continue

        # it's ok if there is no OCR result for videos
        if meme["ocr_result"]:
            duplicate_meme_id = await find_meme_duplicate(meme["id"], meme["ocr_result"]["text"])
            if duplicate_meme_id:
                await resolve_meme_duplicate(meme["id"], duplicate_meme_id)
                continue

    # next step of a pipeline
    await update_meme_status_of_ready_memes()

    safe_emit(
        "ff.pipeline.final.completed",
        "ff.pipeline.final",
        {"memes_processed": len(memes)},
    )
