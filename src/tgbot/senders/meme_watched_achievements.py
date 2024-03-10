from telegram.constants import ParseMode

from src import localizer
from src.tgbot.bot import bot


async def send_meme_watched_achievement_if_needed(
    user_id: int, user_info: dict
) -> bool:
    """Send achievement about watching a certain amount of memes if needed

    returns: True if achievement was sent, False otherwise
    """
    memes_sent_count = user_info["nmemes_sent"]
    meme_count_alerts = (100, 500, 1000, 5000, 10000, 50000, 100000)

    if memes_sent_count not in meme_count_alerts:
        return False

    text_localizer_name = f"achievement_{memes_sent_count}_meme_sent"
    await bot.send_message(
        chat_id=user_id,
        text=localizer.t(text_localizer_name, user_info["interface_lang"]),
        parse_mode=ParseMode.HTML,
    )
    return True
