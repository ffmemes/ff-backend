import asyncio
import logging
from string import punctuation
from typing import Any

from prefect import flow, get_run_logger

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


async def ocr_meme_content(
    meme_id: int, content: bytes, language: str
) -> dict[str, Any] | None:
    logging.debug(f"OCRing meme {meme_id} content.")
    for _ in range(5):  # attempts
        result = await ocr_content(content, language)
        if isinstance(result, OcrResult):
            s = result.text.translate(str.maketrans("", "", punctuation)).lower()
            result.text = " ".join(s.split())
            return await update_meme(meme_id, ocr_result=result.model_dump(mode="json"))
        else:
            logging.warning(msg=f"OCR: {str(result)} {meme_id=}")

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


async def add_watermark_to_meme_content(
    meme_content: bytes, meme_type: MemeType
) -> bytes:
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


@flow(
    name="Memes from Telegram Pipeline",
    description="Process raw memes parsed from Telegram",
    version="0.1.0",
    log_prints=True,
)
async def tg_meme_pipeline() -> None:
    logger = get_run_logger()

    logger.info("ETLing memes from 'meme_raw_telegram' table.")
    await etl_memes_from_raw_telegram_posts()

    logger.info("Getting unloaded memes to upload to Telegram.")
    unloaded_memes = await get_unloaded_tg_memes(limit=100)
    logger.info(f"Received {len(unloaded_memes)} memes to upload to Telegram.")
    for unloaded_meme in unloaded_memes:
        meme = await upload_meme_to_telegram(unloaded_meme)
        if not meme or meme["type"] != MemeType.IMAGE:
            continue

        await ocr_meme_content(
            meme["id"],
            meme["__original_content"],
            meme["language_code"],
        )

    # next step of a pipeline
    await final_meme_pipeline()


@flow(
    name="Memes from VK Pipeline",
    description="Process raw memes parsed from VK",
    version="0.1.0",
)
async def vk_meme_pipeline() -> None:
    logger = get_run_logger()

    logger.info("ETLing memes from 'meme_raw_vk' table.")
    await etl_memes_from_raw_vk_posts()

    logger.info("Getting unloaded memes to upload to Telegram.")
    unloaded_memes = await get_unloaded_vk_memes(limit=100)
    logger.info(f"Received {len(unloaded_memes)}" " memes to upload to Telegram.")
    for unloaded_meme in unloaded_memes:
        meme = await upload_meme_to_telegram(unloaded_meme)
        if not meme or meme["type"] != MemeType.IMAGE:
            continue

        await ocr_meme_content(
            meme["id"],
            meme["__original_content"],
            meme["language_code"],
        )

    # next step of a pipeline
    await final_meme_pipeline()


@flow(
    name="Memes from Instagram Pipeline",
    description="Process raw memes parsed from IG",
    version="0.1.0",
)
async def ig_meme_pipeline() -> None:
    logger = get_run_logger()

    logger.info("ETLing memes from 'meme_raw_vk' table.")
    await etl_memes_from_raw_ig_posts()

    logger.info("Getting unloaded memes to upload to Telegram.")
    unloaded_memes = await get_unloaded_ig_memes(limit=100)
    logger.info(f"Received {len(unloaded_memes)}" " memes to upload to Telegram.")
    for unloaded_meme in unloaded_memes:
        meme = await upload_meme_to_telegram(unloaded_meme)
        if not meme or meme["type"] != MemeType.IMAGE:
            continue

        await ocr_meme_content(
            meme["id"],
            meme["__original_content"],
            meme["language_code"],
        )

        await asyncio.sleep(3)  # flood control

    # next step of a pipeline
    await final_meme_pipeline()


@flow
async def ocr_uploaded_memes(limit=10):
    """
    Download original meme content one more time & OCR it.
    We can't use meme.telegram_file_id because it is already watermarked.
    Runs each 5 mins.
    """
    logger = get_run_logger()
    memes = await get_memes_to_ocr(limit=limit)
    logger.info(f"Going to OCR {len(memes)} memes.")

    for meme in memes:
        if meme["content_url"] is not None:
            meme_original_content = await download_meme_content_file(
                meme["content_url"]
            )
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

        await ocr_meme_content(
            meme["id"],
            meme_original_content,
            meme["language_code"],
        )

    await final_meme_pipeline()


@flow(name="Final Memes Pipeline")
async def final_meme_pipeline() -> None:
    logger = get_run_logger()

    memes = await get_pending_memes()
    logger.info(f"Final meme pipeline has {len(memes)} pending memes.")

    for meme in memes:
        await analyse_meme_caption(meme)

        # it's ok if there is no OCR result for videos
        if meme["ocr_result"]:
            duplicate_meme_id = await find_meme_duplicate(
                meme["id"], meme["ocr_result"]["text"]
            )
            if duplicate_meme_id:
                await update_meme(
                    meme["id"],
                    status=MemeStatus.DUPLICATE,
                    duplicate_of=duplicate_meme_id,
                )
                continue

    # next step of a pipeline
    await update_meme_status_of_ready_memes()
