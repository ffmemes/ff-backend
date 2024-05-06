from telegram import Bot, Message

from src import localizer

# from src.tgbot.senders.keyboards import queue_empty_alert_keyboard
from src.tgbot.user_info import get_user_info


async def send_queue_preparing_alert(bot: Bot, user_id: int) -> Message:
    user_info = await get_user_info(user_id)
    return await bot.send_message(
        chat_id=user_id,
        text=localizer.t("service.out_of_memes", user_info["interface_lang"]),
        # reply_markup=queue_empty_alert_keyboard(),
    )
