import asyncio
from typing import Any
from prefect import flow, get_run_logger

from src.storage.service import (
    etl_memes_from_raw_telegram_posts,
    etl_memes_from_raw_vk_posts,
    get_unloaded_tg_memes,
    get_unloaded_vk_memes,
    get_pending_memes,
    get_memes_to_ocr,
    update_meme_status_of_ready_memes,
    update_meme,
)

from src.storage.upload import (
    download_meme_content_file, 
    upload_meme_content_to_tg,
    download_meme_content_from_tg,
)

from src.storage import ads
from src.storage.ocr.mystic import ocr_content
from src.storage.constants import MemeStatus
from src.storage.watermark import add_watermark


async def ocr_meme_content(meme_id: int, content: bytes):
    result = await ocr_content(content)
    if result:
        await update_meme(meme_id, ocr_result=result.model_dump(mode='json'))


async def analyse_meme_caption(meme_id: int, caption: str | None):
    if ads.text_is_adverisement(caption):
        await update_meme(meme_id, status=MemeStatus.AD)
        return

    new_caption = ads.filter_caption(caption)
    if new_caption != caption:
        await update_meme(meme_id, caption=new_caption)


@flow
async def upload_memes_to_telegram(unloaded_memes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    logger = get_run_logger()
    logger.info(f"Received {len(unloaded_memes)} memes to upload to Telegram.")

    memes = []
    for unloaded_meme in unloaded_memes:
        try:
            logger.info(f"Downloading meme {unloaded_meme['id']} content file.")
            meme_original_content = await download_meme_content_file(unloaded_meme["content_url"])
        except Exception as e:
            logger.info(f"Meme {unloaded_meme['id']} content is not available to download, reason: {e}.")
            await update_meme(unloaded_meme["id"], status=MemeStatus.BROKEN_CONTENT_LINK)
            continue
        
        logger.info(f"Adding watermark to meme {unloaded_meme['id']}.")
        meme_content = add_watermark(meme_original_content)
        if meme_content is None:
            logger.info(f"Meme {unloaded_meme['id']} was not watermarked, skipping.")
            continue

        meme = await upload_meme_content_to_tg(unloaded_meme["id"], unloaded_meme["type"], meme_content)
        await asyncio.sleep(2)  # flood control
        if meme is None:
            logger.info(f"Meme {unloaded_meme['id']} was not uploaded to Telegram, skipping.")
            continue

        meme["__original_content"] = meme_original_content  # HACK: to save original content for OCR
        memes.append(meme)

    return memes


@flow(
    name="Memes from Telegram Pipeline",
    description="Process raw memes parsed from Telegram",
    version="0.1.0",
    log_prints=True,
)
async def tg_meme_pipeline() -> None:
    logger = get_run_logger()

    logger.info(f"ETLing memes from 'meme_raw_telegram' table.")
    await etl_memes_from_raw_telegram_posts()

    logger.info(f"Getting unloaded memes to upload to Telegram.")
    unloaded_memes = await get_unloaded_tg_memes()
    memes = await upload_memes_to_telegram(unloaded_memes)

    for meme in memes:
        await ocr_meme_content(meme["id"], meme["__original_content"])

    # next step of a pipeline
    await final_meme_pipeline()


@flow(
    name="Memes from VK Pipeline",
    description="Process raw memes parsed from VK",
    version="0.1.0"
)
async def vk_meme_pipeline() -> None:
    logger = get_run_logger()

    logger.info(f"ETLing memes from 'meme_raw_vk' table.")
    await etl_memes_from_raw_vk_posts()

    logger.info(f"Getting unloaded memes to upload to Telegram.")
    unloaded_memes = await get_unloaded_vk_memes()
    memes = await upload_memes_to_telegram(unloaded_memes)

    for meme in memes:
        await ocr_meme_content(meme["id"], meme["__original_content"])

    # next step of a pipeline
    await final_meme_pipeline()



@flow(name="Final Memes Pipeline")
async def final_meme_pipeline() -> None:
    logger = get_run_logger()

    memes = await get_pending_memes()
    logger.info(f"Final meme pipeline has {len(memes)} pending memes.")

    for meme in memes:
        await analyse_meme_caption(meme["id"], meme["caption"])

    # next step of a pipeline
    await update_meme_status_of_ready_memes()


@flow
async def ocr_uploaded_memes(limit=100):
    logger = get_run_logger()
    memes = await get_memes_to_ocr(limit=limit)
    logger.info(f"Going to OCR {len(memes)} memes.")

    for meme in memes:
        meme_content = await download_meme_content_from_tg(meme["telegram_file_id"])
        await ocr_meme_content(meme["id"], meme_content)
        await asyncio.sleep(2)  # flood control
