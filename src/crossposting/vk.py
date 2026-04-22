"""
VK community wall posting via raw httpx.

Mirrors the parser pattern in src/storage/parsers/vk.py but for the write side.
Uses a USER access token (settings.VK_USER_TOKEN), not a community token —
photos.getWallUploadServer rejects community tokens with error 27 (long-standing
VK quirk; community tokens nominally have `photos` scope but VK blocks the
upload endpoints). The token must have `wall + photos + offline` scopes and
the user must be admin/creator of the target community. Posts go up via
`from_group=1` so they appear as published by the community, not the user.

Photos only. Video upload (video.save) also requires user token + `video` scope;
not implemented because EN-channel data showed videos hurt engagement
(avg views −56% post-flip).
"""

import json
import logging
from typing import Any

import httpx

from src.config import settings

logger = logging.getLogger(__name__)

VK_API_BASE = "https://api.vk.com/method"
VK_API_VERSION = "5.199"


class VkError(Exception):
    """VK API returned an error or unexpected response shape."""


def _check_response(method: str, payload: dict[str, Any]) -> dict[str, Any]:
    if "error" in payload:
        err = payload["error"]
        raise VkError(f"VK {method} error {err.get('error_code')}: {err.get('error_msg')}")
    if "response" not in payload:
        raise VkError(f"VK {method} unexpected response: {payload}")
    return payload["response"]


async def post_photo_to_group(image_bytes: bytes, caption: str = "") -> dict[str, Any]:
    """Post a single photo to the configured VK community wall.

    Returns the wall.post response: {"post_id": <int>}.
    Raises VkError on any failure in the 3-step upload chain.
    """
    if not settings.VK_USER_TOKEN or settings.VK_GROUP_ID is None:
        raise VkError("VK_USER_TOKEN and VK_GROUP_ID must be configured")

    group_id_positive = abs(settings.VK_GROUP_ID)
    owner_id_negative = -abs(settings.VK_GROUP_ID)
    common = {"access_token": settings.VK_USER_TOKEN, "v": VK_API_VERSION}

    async with httpx.AsyncClient(timeout=60) as client:
        # 1. Get the per-call upload server URL
        r = await client.get(
            f"{VK_API_BASE}/photos.getWallUploadServer",
            params={**common, "group_id": group_id_positive},
        )
        r.raise_for_status()
        upload_url = _check_response("photos.getWallUploadServer", r.json())["upload_url"]

        # 2. Multipart-upload the JPEG to that URL
        r = await client.post(
            upload_url,
            files={"photo": ("meme.jpg", image_bytes, "image/jpeg")},
        )
        r.raise_for_status()
        upload_result = r.json()
        if "photo" not in upload_result or not upload_result.get("photo"):
            raise VkError(f"VK photo upload returned empty: {upload_result}")

        # 3. Save the uploaded photo to the community album
        r = await client.get(
            f"{VK_API_BASE}/photos.saveWallPhoto",
            params={
                **common,
                "group_id": group_id_positive,
                "server": upload_result["server"],
                "photo": upload_result["photo"],
                "hash": upload_result["hash"],
            },
        )
        r.raise_for_status()
        saved = _check_response("photos.saveWallPhoto", r.json())
        if not saved:
            raise VkError("photos.saveWallPhoto returned empty list")
        attachment = f"photo{saved[0]['owner_id']}_{saved[0]['id']}"

        # 4. Publish the wall post
        r = await client.post(
            f"{VK_API_BASE}/wall.post",
            data={
                **common,
                "owner_id": owner_id_negative,
                "from_group": 1,
                "attachments": attachment,
                "message": caption,
            },
        )
        r.raise_for_status()
        result = _check_response("wall.post", r.json())

    logger.info(f"VK posted: {json.dumps(result)} attachment={attachment}")
    return result
