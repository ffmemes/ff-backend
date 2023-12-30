import httpx
from typing import Any
from prefect import flow, task, get_run_logger

from src.storage.service import (
    etl_memes_from_raw_telegram_posts,
    get_unloaded_tg_memes,
    update_meme,
)

from src.storage.upload import (
    download_meme_content_file, 
    upload_meme_content_to_tg,
)

from src.storage.ads import text_is_adverisement, filter_caption
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
        except httpx.HTTPStatusError:
            logger.info(f"Meme {unloaded_meme['id']} content is not available to download.")
            await update_meme(unloaded_meme["id"], status=MemeStatus.BROKEN_CONTENT_LINK)
            continue

        meme_content = add_watermark(meme_original_content)

        meme = await upload_meme_content_to_tg(unloaded_meme["id"], unloaded_meme["type"], meme_content)
        meme["__original_content"] = meme_original_content
        memes.append(meme)

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

    logger.info(f"Checking {len(memes)} memes for ads.")
    for meme in memes:
        if text_is_adverisement(meme["caption"]):
            await update_meme(meme["id"], status=MemeStatus.AD)

        new_caption = filter_caption(meme["caption"])
        if new_caption != meme["caption"]:
            await update_meme(meme["id"], caption=new_caption)

    
