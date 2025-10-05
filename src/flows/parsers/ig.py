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
        user_info = data.get("ig_user_info")

        if not user_info or user_info.get("pk") is None:
            logger.info(f"Getting user info for @{ig_username}")
            fetched_user_info = await get_user_info(ig_username)

            if not fetched_user_info or fetched_user_info.get("pk") is None:
                logger.warning(
                    f"Could not retrieve user info for @{ig_username}, skipping source"
                )
                user_info = {
                    "username": ig_username,
                    "not_found": True,
                    "parsed_at": str(datetime.utcnow()),
                }
            else:
                user_info = {
                    "pk": fetched_user_info.get("pk"),
                    "full_name": fetched_user_info.get("full_name"),
                    "is_private": fetched_user_info.get("is_private"),
                    "username": fetched_user_info.get("username"),
                    "biography": fetched_user_info.get("biography"),
                    "category": fetched_user_info.get("category"),
                    "follower_count": fetched_user_info.get("follower_count"),
                    "following_count": fetched_user_info.get("following_count"),
                    "media_count": fetched_user_info.get("media_count"),
                    "external_url": fetched_user_info.get("external_url"),
                    "parsed_at": str(datetime.utcnow()),
                }

            data = data | {"ig_user_info": user_info}
            await update_meme_source(ig_source["id"], data=data)

        user_info = data.get("ig_user_info")
        if not user_info:
            logger.warning(
                f"Instagram user info missing for source {ig_source['id']}, skipping"
            )
            continue

        if user_info.get("not_found"):
            logger.warning(f"Instagram user @{ig_username} not found, skipping")
            continue

        if user_info.get("is_private"):
            logger.warning(f"@{ig_username} is private, skipping")
            continue

        await parse_ig_source(ig_source["id"], user_info["pk"])

    await ig_meme_pipeline()
