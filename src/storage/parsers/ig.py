from typing import Any

import httpx
import telegram
from pydantic import AnyHttpUrl

from src.config import settings
from src.storage.constants import MemeStatus, MemeType
from src.storage.parsers.constants import USER_AGENT
from src.storage.service import update_meme
from src.tgbot.bot import bot


async def get_user_info(
    username: str,
) -> dict | None:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            "https://api.hikerapi.com/v2/user/by/username",
            params={"username": username},
            headers={"User-Agent": USER_AGENT},
        )

        response.raise_for_status()
        return response.json()


async def get_user_medias(
    user_id: int,
) -> dict | None:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            "https://api.hikerapi.com/v2/user/medias",
            params={"user_id": user_id},
            headers={"User-Agent": USER_AGENT},
        )

        response.raise_for_status()
        return response.json()
