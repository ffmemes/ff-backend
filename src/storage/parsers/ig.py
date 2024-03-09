import logging
from datetime import datetime

import httpx

from src.config import settings
from src.storage.parsers.schemas import IgPostParsingResult


async def _get_user_info(
    username: str,
) -> dict | None:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            "https://api.hikerapi.com/v2/user/by/username",
            params={"username": username},
            headers={
                "accept": "application/json",
                "x-access-key": settings.HIKERAPI_TOKEN,
            },
        )

        response.raise_for_status()
        return response.json()


async def _get_user_medias(
    user_id: int,
) -> dict | None:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            "https://api.hikerapi.com/v2/user/medias",
            params={"user_id": user_id},
            headers={
                "accept": "application/json",
                "x-access-key": settings.HIKERAPI_TOKEN,
            },
        )

        response.raise_for_status()
        return response.json()


async def get_user_info(instagram_username: str):
    user_info_response = await _get_user_info(instagram_username)
    if user_info_response["status"] != "ok" or not user_info_response.get("user"):
        logging.warning(
            f"Failed to get @{instagram_username} info. Result: {user_info_response}"
        )
        return None

    return user_info_response["user"]


async def get_user_medias(user_id: int) -> list[IgPostParsingResult] | None:
    user_medias_response = await _get_user_medias(user_id)
    if user_medias_response["response"]["status"] != "ok":
        logging.warning(f"Failed to get {user_id} medias: {user_medias_response}")
        return None

    medias = user_medias_response["response"]["items"]
    logging.info(f"Received {len(medias)} medias for {user_id}")

    # serialize medias
    return [
        IgPostParsingResult(
            post_id=media["pk"],
            published_at=datetime.fromtimestamp(media["taken_at"]),
            url="https://instagram.com/p/" + media["code"],
            likes=media.get("like_count"),
            views=media.get("play_count"),
            shares=media.get("reshare_count"),
            video_duration=media.get("video_duration"),
            media_type=media["media_type"],
            caption=(media.get("caption") or {}).get("text"),
            media=media.get("video_versions")
            or media.get("image_versions2", {}).get("candidates")
            or media.get("image_versions"),
            comments=media.get("comment_count"),
            product_type=media.get("product_type"),
        )
        for media in medias
    ]
