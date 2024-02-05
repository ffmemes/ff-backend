import asyncio
from datetime import datetime

from prefect import flow, get_run_logger

from src.flows.storage.memes import vk_meme_pipeline
from src.storage.parsers.vk import VkGroupScraper
from src.storage.service import (
    get_vk_sources_to_parse,
    insert_parsed_posts_from_vk,
    update_meme_source,
)


@flow(name="Parse VK Source")
async def parse_vk_source(
    meme_source_id: int,
    meme_source_url: str,
    nposts: int = 10,
) -> None:
    logger = get_run_logger()

    vk = VkGroupScraper(meme_source_url)
    posts = await vk.get_items(nposts)

    logger.info(f"Received {len(posts)} posts from {meme_source_url}")
    if len(posts) > 0:
        await insert_parsed_posts_from_vk(meme_source_id, posts)

    await update_meme_source(meme_source_id=meme_source_id, parsed_at=datetime.utcnow())
    await asyncio.sleep(5)


@flow(
    name="Parse VK Groups",
    description="Flow for parsing vk groups to get posts",
)
async def parse_vk_sources(
    sources_batch_size=10,
    nposts=10,
) -> None:
    logger = get_run_logger()
    vk_sources = await get_vk_sources_to_parse(limit=sources_batch_size)
    logger.info(f"Received {len(vk_sources)} vk sources to scrape.")

    for vk_source in vk_sources:
        await parse_vk_source(vk_source["id"], vk_source["url"], nposts=nposts)

    await vk_meme_pipeline()
