import asyncio
from telegram.constants import ParseMode

from src.tgbot import bot
from src.tgbot.constants import UserType
from src.tgbot.user_info import get_user_info


async def send_achievement_if_needed(user_id: int) -> None:
    user_info = await get_user_info(user_id)
    if user_info["type"] == UserType.USER and user_info["nmemes_sent"] > 1000:
        await bot.application.bot.send_message(
            chat_id=user_id,
            text="Do you wanna be a Moderator?",
            parse_mode=ParseMode.HTML,
        )
        await asyncio.sleep(3)
        return
    
    if user_info["nmemes_sent"] == 100:
        await bot.application.bot.send_message(
            chat_id=user_id,
            text="You've watched 100 memes!",
            parse_mode=ParseMode.HTML,
        )
        await asyncio.sleep(3)
        return

    
    