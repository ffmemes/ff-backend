from prefect import flow, get_run_logger
from datetime import datetime

from src.storage.parsers import telegram
from src.storage.service import (
    get_telegram_sources_to_parse,
    insert_parsed_posts_from_telegram,
    update_meme_source,
)
from src.flows.storage.memes import tg_meme_pipeline


@flow(
    name="Parse Telegram Channels",
    description="Flow for parsing telegram channels to get posts",
    version="0.1.0"
)
async def parse_telegram_sources(
    sources_batch_size=10,
    nposts=10,
) -> None:
    logger = get_run_logger()
    tg_sources = await get_telegram_sources_to_parse(limit=sources_batch_size)
    logger.info(f"Received {len(tg_sources)} tg sources to scrape.")

    for tg_source in tg_sources:
        tg_username = tg_source["url"].split("/")[-1]  # is it ok?

        # TODO: make scrapper async
        posts = telegram.parse_tg_channel(tg_username, num_of_posts=nposts)
        logger.info(f"Received {len(posts)} posts from @{tg_username}")

        await insert_parsed_posts_from_telegram(tg_source["id"], posts)

        await update_meme_source(meme_source_id=tg_source["id"], parsed_at=datetime.utcnow())

    
    await tg_meme_pipeline()
