from telegram import Message

from src import localizer
from src.tgbot.bot import bot
from src.tgbot.senders.keyboards import queue_empty_alert_keyboard
from src.tgbot.user_info import get_user_info


async def send_queue_preparing_alert(user_id: int) -> Message:
    user_info = await get_user_info(user_id)
    return await bot.send_message(
        chat_id=user_id,
        text=localizer.t("service_out_of_memes", user_info["language_code"]),
        reply_markup=queue_empty_alert_keyboard(),
    )
