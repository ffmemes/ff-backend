from telegram import Bot

from src.config import settings

async def log(text: str) -> None:
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    await bot.send_message(
        chat_id=settings.ADMIN_LOGS_CHAT_ID,
        text=text,
        parse_mode="HTML",
    )