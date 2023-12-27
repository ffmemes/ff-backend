from prefect import flow
from datetime import datetime

from src.storage.parsers import telegram
from src.storage.service import (
    get_telegram_sources_to_parse,
    insert_parsed_posts_from_telegram,
    update_meme_source,
)


@flow(
    name="Parse Telegram Channels",
    description="Flow for parsing telegram channels to get posts",
    version="0.1.0"
)
async def parse_telegram_sources(limit=10) -> None:
    tg_sources = await get_telegram_sources_to_parse(limit=limit)

    for tg_source in tg_sources:
        tg_username = tg_source["url"].split("/")[-1]  # is it ok?

        # TODO: make scrapper async
        posts = telegram.parse_tg_channel(tg_username)
        await insert_parsed_posts_from_telegram(tg_source["id"], posts)

        await update_meme_source(meme_source_id=tg_source["id"], parsed_at=datetime.utcnow())
