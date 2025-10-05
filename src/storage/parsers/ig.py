import logging
from datetime import datetime

import httpx

from src.config import settings
from src.storage.parsers.schemas import IgPostParsingResult


HIKERAPI_BASE_URL = "https://api.hikerapi.com/v2"
HIKERAPI_HEADERS = {
    "accept": "application/json",
    "x-access-key": settings.HIKERAPI_TOKEN,
}


async def _fetch_hikerapi(  # pragma: no cover - thin wrapper around httpx
    endpoint: str,
    *,
    params: dict[str, str | int],
    not_found_message: str,
) -> dict | None:
    async with httpx.AsyncClient(base_url=HIKERAPI_BASE_URL, timeout=20.0) as client:
        try:
            response = await client.get(endpoint, params=params, headers=HIKERAPI_HEADERS)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logging.warning(not_found_message)
                return None

            raise
        except httpx.RequestError as exc:
            logging.error("Failed to reach HikerAPI endpoint %s: %s", endpoint, exc)
            raise

        return response.json()


async def _get_user_medias(
    user_id: int,
) -> dict | None:
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            response = await client.get(
                "https://api.hikerapi.com/v2/user/medias",
                params={"user_id": user_id},
                headers={
                    "accept": "application/json",
                    "x-access-key": settings.HIKERAPI_TOKEN,
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logging.warning(
                    "Instagram user with id '%s' not found. Skipping.",
                    user_id,
                )
                return None

            raise

        return response.json()


async def get_user_info(instagram_username: str):
    user_info_response = await _get_user_info(instagram_username)
    if not user_info_response:
        return None

    status = user_info_response.get("status")
    user = user_info_response.get("user")
    if status != "ok" or not user:
        logging.warning(
            "Failed to get @%s info. Result: %s",
            instagram_username,
            user_info_response,
        )
        return None

    return user


async def get_user_medias(user_id: int) -> list[IgPostParsingResult]:
    user_medias_response = await _get_user_medias(user_id)
    if not user_medias_response:
        return None
    if user_medias_response["response"]["status"] != "ok":
        logging.warning(f"Failed to get {user_id} medias: {user_medias_response}")
        return None

    logging.info("Received %s medias for %s", len(medias), user_id)

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
