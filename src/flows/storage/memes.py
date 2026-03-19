import asyncio
from string import punctuation
from typing import Any

from prefect import flow, get_run_logger

from src.config import settings
from src.flows.events import safe_emit
from src.flows.hooks import notify_telegram_on_failure
from src.storage import ads
from src.storage.constants import MemeSourceType, MemeStatus, MemeType
from src.storage.etl import (
    etl_memes_from_raw_ig_posts,
    etl_memes_from_raw_telegram_posts,
    etl_memes_from_raw_vk_posts,
)
from src.storage.ocr.modal import ocr_content
from src.storage.schemas import OcrResult
from src.storage.service import (
    find_meme_duplicate,
    find_meme_duplicate_by_file_id,
    get_memes_to_ocr,
    get_pending_memes,
    get_unloaded_ig_memes,
    get_unloaded_tg_memes,
    get_unloaded_vk_memes,
    update_meme,
    update_meme_status_of_ready_memes,
)
from src.storage.upload import (
    download_meme_content_file,
    download_meme_content_from_tg,
    upload_meme_content_to_tg,
)
from src.storage.watermark import add_watermark
from src.tgbot.handlers.upload.service import (
    get_meme_raw_upload_by_id,
)


async def ocr_meme_content(meme_id: int, content: bytes, language: str) -> dict[str, Any] | None:
    logger = get_run_logger()
    if not settings.OCR_ENABLED:
        logger.info(
            "Skipping OCR for meme %s because OCR_ENABLED is disabled. "
            "Set OCR_ENABLED=true to re-enable OCR.",
            meme_id,
        )
        return True
    logger.debug(f"OCRing meme {meme_id} content.")
    if language not in ("en", "ru"):
        logger.info(f"Can't OCR meme with language_code: {language}")
        return True  # FIXME: to not return NULL and stop the OCR

    for _ in range(1):  # attempts
        result = await ocr_content(content, language)
        if isinstance(result, OcrResult):
            s = result.text.translate(str.maketrans("", "", punctuation)).lower()
            result.text = " ".join(s.split())
            return await update_meme(meme_id, ocr_result=result.model_dump(mode="json"))
        else:
            logger.warning(msg=f"OCR: {str(result)} {meme_id=}")

        await asyncio.sleep(10)  # flood control


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
        if len(set(meme["caption"]) & set("йцукенгшщзхъёфывапролджэячсмитьбю")) > 0:
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

    # HACK: to save original content for OCR
    meme_result["__original_content"] = meme_original_content
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

    if not settings.OCR_ENABLED:
        logger.info("OCR disabled. Memes processed without OCR.")

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

        # Skip OCR for memes already marked as duplicate at upload time
        if meme.get("status") == MemeStatus.DUPLICATE:
            continue

        if settings.OCR_ENABLED and meme["type"] == MemeType.IMAGE:
            res = await ocr_meme_content(
                meme["id"],
                meme["__original_content"],
                meme["language_code"],
            )
            if res is None:
                logger.warning("OCR service unavailable, skipping OCR for rest of batch.")
                break

    logger.info(
        f"Batch done: {ok_count} uploaded, {fail_count} failed out of {total}."
    )


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
    name="Memes from Instagram Pipeline",
    description="Process raw memes parsed from IG",
    version="0.3.0",
    retries=1,
    retry_delay_seconds=60,
    timeout_seconds=1800,
    on_failure=[notify_telegram_on_failure],
)
async def ig_meme_pipeline() -> None:
    logger = get_run_logger()
    logger.info("ETLing memes from 'meme_raw_ig' table.")
    await etl_memes_from_raw_ig_posts()

    unloaded_memes = await get_unloaded_ig_memes(limit=100)
    await _process_unloaded_memes(unloaded_memes, "Instagram")

    safe_emit("ff.pipeline.ig.completed", "ff.pipeline.ig")


@flow
async def ocr_uploaded_memes(limit=100):
    """
    Download original meme content one more time & OCR it.
    We can't use meme.telegram_file_id because it is already watermarked.
    Runs each 5 mins.
    """
    logger = get_run_logger()
    memes = await get_memes_to_ocr(limit=limit)
    if not settings.OCR_ENABLED:
        logger.info(
            "OCR is disabled. Skipping OCR for uploaded memes. "
            "Set OCR_ENABLED=true to re-enable OCR."
        )
        await final_meme_pipeline()
        return

    logger.info(f"Going to OCR {len(memes)} memes.")

    for meme in memes:
        if meme["content_url"] is not None:
            meme_original_content = await download_meme_content_file(meme["content_url"])
            await asyncio.sleep(2)  # flood control

        elif meme["meme_source_type"] == MemeSourceType.USER_UPLOAD:
            meme_raw_upload = await get_meme_raw_upload_by_id(meme["raw_meme_id"])
            meme_original_file_id = meme_raw_upload["media"]["file_id"]
            meme_original_content = await download_meme_content_from_tg(
                meme_original_file_id,
            )
            await asyncio.sleep(2)  # flood control

        else:
            logger.warning(f"Failed to extract #{meme['id']} content_url, skipping.")
            continue

        if meme_original_content is None:
            logger.info(f"Meme {meme['id']} content is not available to download.")
            await update_meme(meme["id"], status=MemeStatus.BROKEN_CONTENT_LINK)
            continue

        res = await ocr_meme_content(
            meme["id"],
            meme_original_content,
            meme["language_code"],
        )

        if res is None:
            logger.warning(
                """
org_meme_content returned NULL, meaning OCR doesn't work.
To save on quota I quit from tg_meme_pipeline
"""
            )
            return

    await final_meme_pipeline()


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
    if not settings.OCR_ENABLED:
        logger.info(
            "OCR is disabled. Duplicates will only be detected for memes with "
            "existing OCR payloads. Set OCR_ENABLED=true to restore full OCR checks."
        )

    for meme in memes:
        await analyse_meme_caption(meme)

        # exact file_id dedup: catches cross-source reposts of identical files
        if meme["telegram_file_id"]:
            dup_id = await find_meme_duplicate_by_file_id(
                meme["id"], meme["telegram_file_id"]
            )
            if dup_id:
                await update_meme(
                    meme["id"],
                    status=MemeStatus.DUPLICATE,
                    duplicate_of=dup_id,
                )
                continue

        # it's ok if there is no OCR result for videos
        if meme["ocr_result"]:
            duplicate_meme_id = await find_meme_duplicate(meme["id"], meme["ocr_result"]["text"])
            if duplicate_meme_id:
                await update_meme(
                    meme["id"],
                    status=MemeStatus.DUPLICATE,
                    duplicate_of=duplicate_meme_id,
                )
                continue

    # next step of a pipeline
    await update_meme_status_of_ready_memes()

    safe_emit(
        "ff.pipeline.final.completed",
        "ff.pipeline.final",
        {"memes_processed": len(memes)},
    )
