import asyncio
from datetime import datetime

from prefect import flow, get_run_logger

from src.flows.storage.memes import tg_meme_pipeline
from src.storage.parsers.tg import TelegramChannelScraper
from src.storage.service import (
    get_telegram_sources_to_parse,
    insert_parsed_posts_from_telegram,
    update_meme_source,
)


@flow(name="Parse Telegram Source")
async def parse_telegram_source(
    meme_source_id: int,
    meme_source_url: str,
    nposts: int = 10,
) -> None:
    logger = get_run_logger()

    tg_username = meme_source_url.split("/")[-1]  # is it ok?
    tg = TelegramChannelScraper(tg_username)

    posts = await tg.get_items(nposts)
    logger.info(f"Received {len(posts)} posts from @{tg_username}")
    if len(posts) > 0:
        await insert_parsed_posts_from_telegram(meme_source_id, posts)

    await update_meme_source(meme_source_id=meme_source_id, parsed_at=datetime.utcnow())
    await asyncio.sleep(5)


@flow(
    name="Parse Telegram Channels",
    description="Flow for parsing telegram channels to get posts",
)
async def parse_telegram_sources(
    sources_batch_size=10,
    nposts=10,
) -> None:
    logger = get_run_logger()
    tg_sources = await get_telegram_sources_to_parse(limit=sources_batch_size)
    logger.info(f"Received {len(tg_sources)} tg sources to scrape.")

    for tg_source in tg_sources:
        await parse_telegram_source(tg_source["id"], tg_source["url"], nposts=nposts)

    await tg_meme_pipeline()
