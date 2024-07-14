import asyncio

import telegram
from telegram.constants import ChatMemberStatus

from src.localizer import ALMOST_CIS_LANGUAGES
from src.tgbot.constants import (
    TELEGRAM_CHANNEL_EN_CHAT_ID,
    TELEGRAM_CHANNEL_EN_LINK,
    TELEGRAM_CHANNEL_RU_CHAT_ID,
    TELEGRAM_CHANNEL_RU_LINK,
)
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


async def check_if_user_follows_related_channel(
    bot: telegram.Bot, user_id: int, language_code: str
):
    if language_code in ALMOST_CIS_LANGUAGES:
        channel_id = TELEGRAM_CHANNEL_RU_CHAT_ID
    else:
        channel_id = TELEGRAM_CHANNEL_EN_CHAT_ID

    return await check_if_user_chat_member(bot, user_id, channel_id)


def get_related_channel_link(language_code: str) -> str:
    if language_code in ALMOST_CIS_LANGUAGES:
        return TELEGRAM_CHANNEL_RU_LINK

    return TELEGRAM_CHANNEL_EN_LINK
