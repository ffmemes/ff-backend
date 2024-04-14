"""
    Methods for Meme uploading via bot:
    - user forwards a message
    - user sends a new message
"""


from typing import Sequence

from telegram import InlineKeyboardButton, Update
from telegram.ext import ContextTypes

from src.tgbot.constants import UserType
from src.tgbot.user_info import get_user_info

LANGUAGES = {
    "ru": "🇷🇺 Русский",
    "en": "🇺🇸 English 🇬🇧",
}

LANG_SETTINGS_END_CALLBACK_DATA = "upload:lang:other"


def get_meme_language_selector_keyboard(meme_id: int) -> list[list[dict]]:
    all_lang_buttons = []
    for lang, lang_text in LANGUAGES.items():
        callback_data = f"l:{lang}:add"
        button_text = lang_text or lang

        all_lang_buttons.append(
            InlineKeyboardButton(button_text, callback_data=callback_data)
        )

    languages_per_row = 2
    lang_keyboard = [
        all_lang_buttons[i : i + languages_per_row]
        for i in range(0, len(all_lang_buttons), languages_per_row)
    ]

    lang_keyboard += [
        [
            InlineKeyboardButton(
                "Other language",
                callback_data=LANG_SETTINGS_END_CALLBACK_DATA,
            )
        ],
    ]

    return lang_keyboard


# callback_data = LANG_SETTINGS_END_CALLBACK_DATA
async def handle_meme_upload_lang_other(
    update: Update,
    _: ContextTypes.DEFAULT_TYPE,
) -> None:
    await update.effective_user.send_message(
        """
We can easily add the language you need. Just send us a message with /chat command.

Example:
/chat Please add english language!

Remember that you can't select the wrong language for meme for now.
        """
    )


async def handle_forward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """When a user forwards a tg message to a bot"""
    print(update)

    att = update.message.effective_attachment
    print(att)

    user = await get_user_info(update.effective_user.id)
    if user["type"] != UserType.ADMIN:
        return await update.message.reply_text(
            "You are not allowed to upload memes.\n\n\n\n\n\n\nYET!"
        )

    if isinstance(update.message.effective_attachment, Sequence):
        return await update.message.reply_text(
            "Message with only one media supported\n\n\n\n\n\n\nYET!"
        )

    # update.message.effective_attachment

    # get_meme_language_selector_keyboard

    # TODO:
    # return meme + caption + keyboard to select a language + rules
    # save meme to a raw_meme_upload with status "created"
    # trigger ETL ?
    # send to modetation

    # TODO: button on language select page: "other language"
    # -> sends a message inviting to send us a message with /chat
    # asking to add the language

    # meme is valid if:
    # language is correct
    # moderators approved the meme


# TODO: do we need separate handlers?
async def handle_message_with_meme(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """When a user sends a message with a meme"""
    print(update)

    user = await get_user_info(update.effective_user.id)
    if user["type"] != UserType.ADMIN:
        return update.message.reply_text(
            "You are not allowed to upload memes.\n\n\n\n\n\n\nYET!"
        )
