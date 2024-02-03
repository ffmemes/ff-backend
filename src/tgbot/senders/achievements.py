import asyncio

from telegram.constants import ParseMode

from src import localizer
from src.tgbot.bot import bot
from src.tgbot.constants import UserType
from src.tgbot.senders.meme_watched_achievements import (
    send_meme_watched_achievement_if_needed,
)
from src.tgbot.user_info import get_user_info

SECONDS_TO_SLEEP_AFTER_NOTIFICATION = 3


async def send_achievement_if_needed(user_id: int) -> None:
    user_info = await get_user_info(user_id)
    if user_info["type"] == UserType.USER and user_info["nmemes_sent"] == 1000:
        await bot.send_message(
            chat_id=user_id,
            text=localizer.t("ask_if_user_wants_to_be_moderator", user_info["interface_lang"]),
            parse_mode=ParseMode.HTML,
        )
        await asyncio.sleep(SECONDS_TO_SLEEP_AFTER_NOTIFICATION)
        return

    is_sent = await send_meme_watched_achievement_if_needed(user_id, user_info)
    if is_sent:
        await asyncio.sleep(SECONDS_TO_SLEEP_AFTER_NOTIFICATION)

