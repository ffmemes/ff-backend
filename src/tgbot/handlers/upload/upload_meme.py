"""
    Methods for Meme uploading via bot:
    - user forwards a message
    - user sends a new message
"""

import asyncio
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from src import localizer
from src.recommendations.meme_queue import check_queue
from src.tgbot.handlers.upload.moderation import uploaded_meme_auto_review
from src.tgbot.handlers.upload.service import (
    count_24h_uploaded_not_approved_memes,
    create_meme_from_meme_raw_upload,
    create_meme_raw_upload,
    update_meme_raw_upload,
)
from src.tgbot.logs import log
from src.tgbot.senders.next_message import next_message
from src.tgbot.user_info import get_user_info
from src.tgbot.utils import (
    check_if_user_follows_related_channel,
    get_related_channel_link,
)

LANGUAGES = {
    "ru": "🇷🇺 Русский",
    "uk": "🇺🇦 Українська",
    "en": "🇺🇸 English 🇬🇧",
    "es": "🇪🇸 Español",
    "ar": "🇸🇦 العربية",
    "uz": "🇺🇿 O'zbekcha",
}

RULES_ACCEPTED_CALLBACK_DATA_PATTERN = "upload:{upload_id}:rules:accepted"
RULES_ACCEPTED_CALLBACK_DATA_REGEXP = r"upload:(\d+):rules:accepted"

LANGUAGE_SELECTED_CALLBACK_DATA_PATTERN = "upload:{upload_id}:lang:{lang}"
LANGUAGE_SELECTED_CALLBACK_DATA_REGEXP = r"upload:(\d+):lang:(\w+)"

LANGUAGE_SELECTED_OTHER_CALLBACK_DATA_PATTERN = "upload:{upload_id}:lang:other"
LANGUAGE_SELECTED_OTHER_CALLBACK_DATA_REGEXP = r"upload:(\d+):lang:other"


def get_meme_language_selector_keyboard(upload_id: int) -> list[list[dict]]:
    all_lang_buttons = []
    for lang, lang_text in LANGUAGES.items():
        button_text = lang_text or lang

        all_lang_buttons.append(
            InlineKeyboardButton(
                button_text,
                callback_data=LANGUAGE_SELECTED_CALLBACK_DATA_PATTERN.format(
                    upload_id=upload_id, lang=lang
                ),
            )
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
                callback_data=LANGUAGE_SELECTED_OTHER_CALLBACK_DATA_PATTERN.format(
                    upload_id=upload_id
                ),
            )
        ],
    ]

    return lang_keyboard


async def handle_message_with_meme(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """When a user sends a message with a meme"""
    user = await get_user_info(update.effective_user.id)
    if user["nmemes_sent"] < 50:
        return await update.message.reply_text(
            localizer.t("upload.watch_memes_to_unblock_upload", user["interface_lang"]),
        )

    uploaded_today = await count_24h_uploaded_not_approved_memes(
        update.effective_user.id
    )
    if uploaded_today >= 5:
        return await update.message.reply_text(
            """
You already uploaded lots of memes today. Try again tomorrow.
Think about quality, not quantity: the goal is to get as many likes as possible.
            """
        )

    meme_upload = await create_meme_raw_upload(update.message)
    # TODO: check that a user uploaded <= N memes today

    if not await check_if_user_follows_related_channel(
        context.bot, update.effective_user.id, user["interface_lang"]
    ):
        return await update.message.reply_text(
            f"""
You need to follow our channel to upload memes and try again:

{get_related_channel_link(user["interface_lang"])}
            """
        )

    await update.message.reply_photo(
        photo=update.message.photo[-1].file_id,
        caption=localizer.t("upload.rules", user["interface_lang"]),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        localizer.t(
                            "upload.rules_accept_button", user["interface_lang"]
                        ),
                        callback_data=RULES_ACCEPTED_CALLBACK_DATA_PATTERN.format(
                            upload_id=meme_upload["id"],
                        ),
                    )
                ]
            ]
        ),
    )


# callback: RULES_ACCEPTED_CALLBACK_DATA
async def handle_rules_accepted_callback(
    update: Update,
    _: ContextTypes.DEFAULT_TYPE,
) -> None:
    # user accepted the rules. Next, we need to ask to specify the language of a meme
    await update.callback_query.answer()
    user_info = await get_user_info(update.effective_user.id)

    upload_id = int(
        re.match(RULES_ACCEPTED_CALLBACK_DATA_REGEXP, update.callback_query.data).group(
            1
        )
    )

    await update.callback_query.message.edit_caption(
        localizer.t("upload.select_language", user_info["interface_lang"]),
        reply_markup=InlineKeyboardMarkup(
            get_meme_language_selector_keyboard(upload_id)
        ),
    )


# callback_data = LANG_SETTINGS_END_CALLBACK_DATA
async def handle_meme_upload_lang_other(
    update: Update,
    _: ContextTypes.DEFAULT_TYPE,
) -> None:
    await update.callback_query.answer()
    user_info = await get_user_info(update.effective_user.id)
    await update.effective_user.send_message(
        localizer.t("upload.we_can_add_language_you_need", user_info["interface_lang"]),
    )


# callback: RULES_ACCEPTED_CALLBACK_DATA
async def handle_meme_upload_lang_selected(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await update.callback_query.answer()
    user_info = await get_user_info(update.effective_user.id)

    reg = re.match(LANGUAGE_SELECTED_CALLBACK_DATA_REGEXP, update.callback_query.data)
    upload_id, lang = int(reg.group(1)), reg.group(2)

    meme_upload = await update_meme_raw_upload(upload_id, language_code=lang)
    meme = await create_meme_from_meme_raw_upload(meme_upload)

    await log(
        f"""📥 Meme {meme["id"]} uploaded by #{update.effective_user.id}""", context.bot
    )

    # TODO: create a meme object from meme_raw_upload

    await update.callback_query.message.edit_caption(
        localizer.t("upload.submitted", user_info["interface_lang"]),
        reply_markup=None,
        parse_mode=ParseMode.HTML,
    )

    asyncio.create_task(uploaded_meme_auto_review(meme, meme_upload, context.bot))
    await check_queue(update.effective_user.id)  # to ensure user has memes in queue
    await asyncio.sleep(5)
    await next_message(context.bot, update.effective_user.id, update)
