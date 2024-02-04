from src.config import settings
from src.tgbot.bot import bot


async def log(text: str) -> None:
    await bot.send_message(
        chat_id=settings.ADMIN_LOGS_CHAT_ID,
        text=text,
        parse_mode="HTML",
    )
