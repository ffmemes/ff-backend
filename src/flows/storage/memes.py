import asyncio
from string import punctuation
from typing import Any

from prefect import flow, get_run_logger
from telegram.error import BadRequest, RetryAfter

from src.storage import ads
from src.storage.constants import MemeStatus, MemeType
from src.storage.ocr.mystic import ocr_content
from src.storage.service import (
    etl_memes_from_raw_telegram_posts,
    etl_memes_from_raw_vk_posts,
    find_meme_duplicate,
    get_memes_to_ocr,
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


async def ocr_meme_content(meme_id: int, content: bytes, language: str):
    result = await ocr_content(content, language)
    if result:
        s = result.text.translate(str.maketrans("", "", punctuation)).lower()
        result.text = " ".join(s.split())
        await update_meme(meme_id, ocr_result=result.model_dump(mode="json"))


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

    for _ in range(3):  # attempts
        try:
            meme = await upload_meme_content_to_tg(
                meme_id=meme["id"],
                meme_type=meme["type"],
                content=watermarked_meme_content,
            )
            if meme:
                break
        except RetryAfter as e:
            logger.warning(f"Flood control exceeded: {e}")
            await asyncio.sleep(e.retry_after)
        except BadRequest as e:
            logger.warning(f"Can't upload. Telegram error: {e}")
            await asyncio.sleep(5)
            return None

        await asyncio.sleep(3)  # flood control

    if meme is None or meme.get("telegram_file_id") is None:
        logger.warning(f"Meme {meme['id']} failed to upload to Telegram.")
        return None

    # HACK: to save original content for OCR
    meme["__original_content"] = meme_original_content
    return meme


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
        if not meme:
            continue

        await ocr_meme_content(
            meme["id"], meme["__original_content"], meme["language_code"]
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
    logger.info(f"Received {len(unloaded_memes)} memes to upload to Telegram.")
    for unloaded_meme in unloaded_memes:
        meme = await upload_meme_to_telegram(unloaded_meme)
        if not meme:
            continue

        await ocr_meme_content(
            meme["id"], meme["__original_content"], meme["language_code"]
        )

    # next step of a pipeline
    await final_meme_pipeline()


@flow
async def ocr_uploaded_memes(limit=100):
    """
    Download original meme content one more time & OCR it.
    We can't use meme.telegram_file_id because it is already watermarked.
    """
    logger = get_run_logger()
    memes = await get_memes_to_ocr(limit=limit)
    logger.info(f"Going to OCR {len(memes)} memes.")

    for meme in memes:
        meme_original_content = await download_meme_content_file(meme["content_url"])
        await asyncio.sleep(3)  # flood control

        if meme_original_content is None:
            logger.info(f"Meme {meme['id']} content is not available to download.")
            await update_meme(meme["id"], status=MemeStatus.BROKEN_CONTENT_LINK)
            continue

        await ocr_meme_content(meme["id"], meme_original_content, meme["language_code"])

    await final_meme_pipeline()


@flow(name="Final Memes Pipeline")
async def final_meme_pipeline() -> None:
    logger = get_run_logger()

    memes = await get_pending_memes()
    logger.info(f"Final meme pipeline has {len(memes)} pending memes.")

    for meme in memes:
        await analyse_meme_caption(meme)

        duplicate_meme_id = await find_meme_duplicate(
            meme["id"], meme["ocr_result"]["text"]
        )
        if duplicate_meme_id:
            await update_meme(
                meme["id"], status=MemeStatus.DUPLICATE, duplicate_of=duplicate_meme_id
            )
            continue

    # next step of a pipeline
    await update_meme_status_of_ready_memes()
