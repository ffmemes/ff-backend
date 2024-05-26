import asyncio
from datetime import datetime

from prefect import flow, get_run_logger

from src.flows.storage.memes import ig_meme_pipeline
from src.storage.etl import insert_parsed_posts_from_ig
from src.storage.parsers.ig import get_user_info, get_user_medias
from src.storage.service import (
    get_ig_sources_to_parse,
    update_meme_source,
)


@flow(name="Parse IG Source")
async def parse_ig_source(
    meme_source_id: int,
    instagram_user_id: int,
) -> None:
    logger = get_run_logger()

    logger.info(f"Going to parse feed ig user id {instagram_user_id}")

    medias = await get_user_medias(instagram_user_id)
    if len(medias) > 0:
        await insert_parsed_posts_from_ig(meme_source_id, medias)

    await update_meme_source(meme_source_id=meme_source_id, parsed_at=datetime.utcnow())
    await asyncio.sleep(5)


@flow(
    name="Parse Instagram Groups",
    description="Flow for parsing instagram profiles to get posts",
)
async def parse_ig_sources(
    sources_batch_size=10,
    # nposts=10,
) -> None:
    logger = get_run_logger()
    ig_sources = await get_ig_sources_to_parse(limit=sources_batch_size)
    logger.info(f"Received {len(ig_sources)} instagram sources to scrape.")

    for ig_source in ig_sources:
        ig_username = ig_source["url"].split("/")[-1]
        logger.info(f"Going to parse ig username: {ig_username}")

        # receiving
        data = ig_source["data"] or {}
        if not data or data.get("pk") is None:
            logger.info(f"Getting user info for @{ig_username}")
            user_info = await get_user_info(ig_username)

            data = (ig_source["data"] or {}) | {
                "ig_user_info": {
                    "pk": user_info["pk"],
                    "full_name": user_info["full_name"],
                    "is_private": user_info["is_private"],
                    "username": user_info["username"],
                    "biography": user_info["biography"],
                    "category": user_info["category"],
                    "follower_count": user_info["follower_count"],
                    "following_count": user_info["following_count"],
                    "media_count": user_info["media_count"],
                    "external_url": user_info["external_url"],
                    "parsed_at": str(datetime.utcnow()),
                }
            }
            await update_meme_source(ig_source["id"], data=data)

        user_info = data["ig_user_info"]
        if user_info["is_private"]:
            logger.warning(f"@{ig_username} is private, skipping")
            continue

        await parse_ig_source(ig_source["id"], user_info["pk"])

    await ig_meme_pipeline()
