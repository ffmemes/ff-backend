from prefect import flow, get_run_logger
from datetime import datetime

from src.storage.parsers.vk import VkGroupScraper
from src.storage.service import (
    get_vk_sources_to_parse,
    insert_parsed_posts_from_vk,
    update_meme_source,
)


@flow(
    name="Parse VK Groups",
    description="Flow for parsing vk groups to get posts",
    version="0.1.0"
)
async def parse_vk_sources(
    sources_batch_size=10,
    nposts=10,
) -> None:
    logger = get_run_logger()
    vk_sources = await get_vk_sources_to_parse(limit=sources_batch_size)
    logger.info(f"Received {len(vk_sources)} tg sources to scrape.")

    for vk_source in vk_sources:
        vk = VkGroupScraper(vk_source["url"])

        posts = await vk.get_items(nposts)
        logger.info(f"Received {len(posts)} posts from {vk_source}")

        await insert_parsed_posts_from_vk(vk_source["id"], posts)

        await update_meme_source(meme_source_id=vk_source["id"], parsed_at=datetime.utcnow())
