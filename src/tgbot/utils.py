import asyncio
import telegram
from telegram.constants import ChatMemberStatus

from src.tgbot.schemas import UserTg
from src.tgbot.service import add_user_tg_chat_membership


def remove_buttons_with_callback(reply_markup: dict) -> dict:
    original_keyboard = reply_markup["inline_keyboard"]

    new_keyboard = []
    for row in original_keyboard:
        filtered_buttons = []
        for button in row:
            if "callback_data" in button:
                continue

            filtered_buttons.append(button)

        new_keyboard.append(filtered_buttons)

    reply_markup["inline_keyboard"] = new_keyboard
    return reply_markup


def tg_user_repr(tg_user: UserTg) -> str:
    return f"@{tg_user.username}" if tg_user.username else f"#{tg_user.id}"


# TODO: move to telegram utils?
async def check_if_user_chat_member(bot: telegram.Bot, user_id: int, chat_id: int):
    try:
        res = await bot.get_chat_member(chat_id, user_id)
        if res.status in [
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.OWNER,
        ]:
            asyncio.create_task(add_user_tg_chat_membership(user_id, chat_id))
            return True
    except telegram.error.BadRequest as e:
        if e.message == "Chat not found":
            raise Exception(f"Add bot to admins of chat_id: {chat_id}")

    return False
