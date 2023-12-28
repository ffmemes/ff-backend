from typing import Any
from prefect import flow, task, get_run_logger

from src.storage.service import (
    etl_memes_from_raw_telegram_posts,
    get_unloaded_tg_memes,
)

from src.storage.upload import (
    download_meme_content_file, 
    upload_meme_content_to_tg,
)


@task
async def upload_memes_to_telegram(unloaded_memes: list[dict[str, Any]]) -> None:
    logger = get_run_logger()
    logger.info(f"Received {len(unloaded_memes)} memes to upload to Telegram.")

    for unloaded_meme in unloaded_memes:
        # TODO: proper try except
        meme_content = await download_meme_content_file(unloaded_meme["url"])
        await upload_meme_content_to_tg(unloaded_meme["id"], unloaded_meme["type"], meme_content)


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
    await upload_memes_to_telegram(unloaded_memes)
