
from telegram import Message

from src.tgbot import bot

from src.tgbot.senders.keyboards import get_queue_empty_alert_keyboard


async def send_queue_preparing_alert(user_id: int) -> Message:
    return await bot.application.bot.send_message(
        chat_id=user_id,
        text="I'm the best memes for you.",
        reply_markup=get_queue_empty_alert_keyboard(),
    )
