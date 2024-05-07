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

LANGUAGES = {
    "ru": "🇷🇺 Русский",
    "uk": "🇺🇦 Українська",
    "en": "🇺🇸 English 🇬🇧",
    "es": "🇪🇸 Español",
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


RULES = """
~ OUR RULES ~
1️⃣ No bullshit content, you know what I mean.
2️⃣ We can reject any post at our discretion.
3️⃣ Meme will be rejected if someone else has already submitted it.
4️⃣ For now, your meme should have only 1 picture.
5️⃣ Providing false info about the meme will lead to a rejection and penalty.
"""


async def handle_message_with_meme(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """When a user sends a message with a meme"""
    user = await get_user_info(update.effective_user.id)
    if user["nmemes_sent"] < 50:
        return await update.message.reply_text(
            "Watch at least 50 memes if you want to share your memes with our community"
        )

    uploaded_today = await count_24h_uploaded_not_approved_memes(
        update.effective_user.id
    )
    if uploaded_today >= 10:
        return await update.message.reply_text(
            """
You already uploaded lots of memes today. Try tomorrow or when we approve something.
            """
        )

    meme_upload = await create_meme_raw_upload(update.message)
    # TODO: check that a user uploaded <= N memes today

    await update.message.reply_photo(
        photo=update.message.photo[-1].file_id,
        caption=f"""
Do you want to share this meme with our community?

{RULES.strip()}
        """,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "I agree",
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

    upload_id = int(
        re.match(RULES_ACCEPTED_CALLBACK_DATA_REGEXP, update.callback_query.data).group(
            1
        )
    )

    await update.callback_query.message.edit_caption(
        """
Please select the language of the meme.

Make sure you select the correct language otherwise your meme will be rejected
and you may receive a penalty.
        """,
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
    await update.effective_user.send_message(
        """
We can easily add the language you need. Just send us a message with /chat command.

Example:
/chat Please add ¬˚µ∆˜ˆ˙®∂∫ language!

Remember that you can't select the wrong language for meme for now.
        """
    )


# callback: RULES_ACCEPTED_CALLBACK_DATA
async def handle_meme_upload_lang_selected(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await update.callback_query.answer()
    reg = re.match(LANGUAGE_SELECTED_CALLBACK_DATA_REGEXP, update.callback_query.data)
    upload_id, lang = int(reg.group(1)), reg.group(2)

    meme_upload = await update_meme_raw_upload(upload_id, language_code=lang)
    meme = await create_meme_from_meme_raw_upload(meme_upload)

    await log(
        f"""📥 Meme {meme["id"]} uploaded by #{update.effective_user.id}""", context.bot
    )

    # TODO: create a meme object from meme_raw_upload

    await update.callback_query.message.edit_caption(
        """
🏁 <b>You submitted your meme for a review.</b>

What to do next:
1. Wait for the approval or rejection from our team.
2. Keep watching other memes!
        """,
        reply_markup=None,
        parse_mode=ParseMode.HTML,
    )

    asyncio.create_task(uploaded_meme_auto_review(meme, meme_upload, context.bot))
    await check_queue(update.effective_user.id)  # to ensure user has memes in queue
    await asyncio.sleep(5)
    await next_message(context.bot, update.effective_user.id, update)
