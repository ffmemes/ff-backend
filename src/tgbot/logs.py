import logging
from html import escape

from telegram import Bot
from telegram.error import BadRequest, NetworkError, TimedOut

from src.config import settings
from src.tgbot.bot import bot as default_bot

logger = logging.getLogger(__name__)


def html_escape(value: object) -> str:
    return escape(str(value), quote=False)


async def log(text: str, bot: Bot | None = None) -> None:
    tg_bot = bot or default_bot
    message = text[:4000]
    try:
        await tg_bot.send_message(
            chat_id=settings.ADMIN_LOGS_CHAT_ID,
            text=message,
            parse_mode="HTML",
        )
    except BadRequest as error:
        if "can't parse entities" not in str(error).lower():
            raise
        logger.warning("Admin log contained invalid Telegram HTML; retrying as plain text")
        await tg_bot.send_message(
            chat_id=settings.ADMIN_LOGS_CHAT_ID,
            text=message,
            parse_mode=None,
        )
    except (NetworkError, TimedOut) as error:
        logger.warning("Admin log delivery failed: %s", error)
