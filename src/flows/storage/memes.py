import httpx
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
)

from src.storage import ads
from src.storage.ocr.mystic import ocr_content
from src.storage.constants import MemeStatus
from src.storage.watermark import add_watermark


@flow
async def upload_memes_to_telegram(unloaded_memes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    logger = get_run_logger()
    logger.info(f"Received {len(unloaded_memes)} memes to upload to Telegram.")

    memes = []
    for unloaded_meme in unloaded_memes:
        
        try:
            meme_original_content = await download_meme_content_file(unloaded_meme["content_url"])
        except Exception as e:
            logger.info(f"Meme {unloaded_meme['id']} content is not available to download, reason: {e}.")
            await update_meme(unloaded_meme["id"], status=MemeStatus.BROKEN_CONTENT_LINK)
            continue

        meme_content = add_watermark(meme_original_content)

        meme = await upload_meme_content_to_tg(unloaded_meme["id"], unloaded_meme["type"], meme_content)
        if meme is None:
            logger.info(f"Meme {unloaded_meme['id']} was not uploaded to Telegram, skipping.")
            continue

        meme["__original_content"] = meme_original_content
        memes.append(meme)

        await asyncio.sleep(1)

    return memes


@flow(
    name="Memes from Telegram Pipeline",
    description="Process raw memes parsed from Telegram",
    version="0.1.0"
)
async def tg_meme_pipeline() -> None:
    logger = get_run_logger()

    logger.info(f"ETLing memes from 'meme_raw_telegram' table.")
    await etl_memes_from_raw_telegram_posts()

    logger.info(f"Getting unloaded memes to upload to Telegram.")
    unloaded_memes = await get_unloaded_tg_memes()
    memes = await upload_memes_to_telegram(unloaded_memes)

    await ocr_meme_content(memes)

    # next step of a pipeline
    await check_captions_of_pending_memes()


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

    await ocr_meme_content(memes)

    # next step of a pipeline
    await check_captions_of_pending_memes()


# I don't want to create a @flow because I already loaded 
# meme file content to RAM and I don't want to load it again
async def ocr_meme_content(memes_with_content):
    logger = get_run_logger()
    logger.info(f"Going to OCR {len(memes_with_content)} pending memes.")

    for meme in memes_with_content:
        if meme["type"] != "image":
            continue

        # INFO: obtained '__original_content' during uploading to tg
        result = await ocr_content(meme["__original_content"])
        if result:
            await update_meme(meme["id"], ocr_result=result)


@flow
async def check_captions_of_pending_memes():
    logger = get_run_logger()
    memes = await get_pending_memes()
    logger.info(f"Checking captions of {len(memes)} pending memes for ads.")

    for meme in memes:
        if ads.text_is_adverisement(meme["caption"]):
            await update_meme(meme["id"], status=MemeStatus.AD)
            continue

        new_caption = ads.filter_caption(meme["caption"])
        if new_caption != meme["caption"]:
            await update_meme(meme["id"], caption=new_caption)

    await update_meme_status_of_ready_memes()
