from telegram import Bot

from src.config import settings
from src.tgbot.bot import bot as default_bot


async def log(text: str, bot: Bot | None = None) -> None:
    await (bot or default_bot).send_message(
        chat_id=settings.ADMIN_LOGS_CHAT_ID,
        text=text,
        parse_mode="HTML",
    )
