import asyncio

from telegram.constants import ParseMode

from src import localizer
from src.tgbot.bot import bot


async def send_meme_watched_achievement_if_needed(user_id: int, user_info: dict) -> bool:
    """Send achievement about watching a certain amount of memes if needed and return True if sent"""
    memes_sent_count = user_info["nmemes_sent"]
    text_localizer_name = None
    if memes_sent_count == 100:
        text_localizer_name = "achievement_100_meme_sent"
    # elif memes_sent_count == 1000:
    #     text_localizer_name = "achievement_1000_meme_sent"

    if text_localizer_name is None:
        return False

    await bot.send_message(
        chat_id=user_id,
        text=localizer.t(text_localizer_name, user_info["interface_lang"]),
        parse_mode=ParseMode.HTML,
    )
    return True
