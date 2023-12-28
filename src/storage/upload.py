import httpx
import telegram
from typing import Any
from pydantic import AnyHttpUrl

from src.config import settings
from src.storage.constants import MemeType
from src.storage.service import update_meme


async def download_meme_content_file(
    url: AnyHttpUrl,
):
    with httpx.Client() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content


async def upload_meme_content_to_tg(
    meme_id: int,
    meme_type: MemeType,
    content: bytes,  # ??
) -> dict[str, Any]:
    bot = telegram.Bot(token=settings.TELEGRAM_BOT_TOKEN)
    if meme_type == MemeType.IMAGE:
        msg = await bot.send_photo(
            chat_id=settings.MEME_STORAGE_TELEGRAM_CHAT_ID, 
            photo=content
        )

        meme = await update_meme(
            meme_id=meme_id,
            telegram_file_id=msg.photo[-1].file_id,
        )
    
    if meme_type == MemeType.VIDEO:
        msg = await bot.send_video(
            chat_id=settings.MEME_STORAGE_TELEGRAM_CHAT_ID, 
            video=content
        )

        meme = await update_meme(
            meme_id=meme_id,
            telegram_file_id=msg.video.file_id,
        )

    if meme_type == MemeType.ANIMATION:
        msg = await bot.send_animation(
            chat_id=settings.MEME_STORAGE_TELEGRAM_CHAT_ID, 
            animation=content
        )

        meme = await update_meme(
            meme_id=meme_id,
            telegram_file_id=msg.animation.file_id,
        )

    return meme