from telegram import Update
from telegram.ext import (
    ContextTypes,
)

from src import localizer
from src.storage.constants import Language
from src.tgbot import service
from src.tgbot.senders.keyboards import user_language_selection_keyboard
from src.tgbot.senders.next_message import next_message
from src.tgbot.service import add_user_language, del_user_language, get_user_languages
from src.tgbot.user_info import cache_user_info, get_user_info


async def handle_language_command_or_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handles /lang, /language command and language selection callback
    """
    user_id = update.effective_user.id
    user_info = await get_user_info(user_id)

    if not update.callback_query:
        languages = tuple(
            Language(i["language_code"]) for i in await get_user_languages(user_id)
        )
        await update.message.reply_text(
            text=localizer.t("choose_your_language", user_info["language_code"]),
            reply_markup=user_language_selection_keyboard(languages)
        )
        return

    data = update.callback_query.data.split(":")
    if data[1] == "set_lang_on":
        await add_user_language(user_id, Language(data[2]))
    elif data[1] == "set_lang_off":
        await del_user_language(user_id, Language(data[2]))
    else:
        raise ValueError(f"Unknown language callback: {data}")

    languages = tuple(
        Language(i["language_code"]) for i in await get_user_languages(user_id)
    )

    await update.callback_query.message.edit_reply_markup(
        reply_markup=user_language_selection_keyboard(languages)
    )

    # TODO: change user's telegram UI language
    # if we detected that their core language is different now

    # update cached user_info
    user_info = await service.get_user_info(user_id)
    await cache_user_info(user_id, user_info)


async def handle_set_language_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user_id = update.effective_user.id
    await update.callback_query.message.delete()
    await next_message(user_id, update)

