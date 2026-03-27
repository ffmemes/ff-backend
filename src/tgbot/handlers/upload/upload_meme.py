"""
Methods for Meme uploading via bot:
- user forwards a message
- user sends a new message
"""

import asyncio
import re
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import ContextTypes

from src import localizer
from src.recommendations.meme_queue import check_queue
from src.tgbot.constants import UserType
from src.tgbot.handlers.upload.constants import SUPPORTED_LANGUAGES
from src.tgbot.handlers.upload.forwarded_meme import (
    extract_meme_id_from_message,
    format_age,
    was_forwarded_from_bot,
)
from src.tgbot.handlers.upload.moderation import uploaded_meme_auto_review
from src.tgbot.handlers.upload.service import (
    count_24h_uploaded_not_approved_memes,
    create_meme_from_meme_raw_upload,
    create_meme_raw_upload,
    update_meme_raw_upload,
)
from src.tgbot.logs import log
from src.tgbot.senders.next_message import next_message
from src.tgbot.service import (
    get_meme_by_id,
    get_meme_source_by_id,
    get_meme_source_stats_by_id,
    get_meme_stats,
)
from src.tgbot.user_info import get_user_info
from src.tgbot.utils import (
    check_if_user_follows_related_channel,
    get_related_channel_link,
)

RULES_ACCEPTED_CALLBACK_DATA_PATTERN = "upload:{upload_id}:rules:accepted"
RULES_ACCEPTED_CALLBACK_DATA_REGEXP = r"upload:(\d+):rules:accepted"

LANGUAGE_SELECTED_CALLBACK_DATA_PATTERN = "upload:{upload_id}:lang:{lang}"
LANGUAGE_SELECTED_CALLBACK_DATA_REGEXP = r"upload:(\d+):lang:(\w+)"

LANGUAGE_SELECTED_OTHER_CALLBACK_DATA_PATTERN = "upload:{upload_id}:lang:other"
LANGUAGE_SELECTED_OTHER_CALLBACK_DATA_REGEXP = r"upload:(\d+):lang:other"


async def _reply_with_forwarded_meme_stats(
    update: Update,
    meme_id: int,
) -> bool:
    message = update.message
    if not message:
        return False

    reply_kwargs = {
        "reply_to_message_id": message.message_id,
        "allow_sending_without_reply": True,
    }

    meme = await get_meme_by_id(meme_id)
    if not meme:
        await message.reply_text(
            f"Не нашёл информацию по мему #{meme_id}.",
            disable_web_page_preview=True,
            **reply_kwargs,
        )
        return True

    meme_source = await get_meme_source_by_id(meme["meme_source_id"])
    if not meme_source:
        await message.reply_text(
            f"Источник мема #{meme_id} не найден.",
            disable_web_page_preview=True,
            **reply_kwargs,
        )
        return True
    meme_stats = await get_meme_stats(meme_id)
    meme_source_stats = await get_meme_source_stats_by_id(meme_source["id"])

    meme_nlikes = meme_stats["nlikes"] if meme_stats else 0
    meme_ndislikes = meme_stats["ndislikes"] if meme_stats else 0
    meme_views = meme_stats["nmemes_sent"] if meme_stats else 0

    source_nlikes = meme_source_stats["nlikes"] if meme_source_stats else 0
    source_ndislikes = meme_source_stats["ndislikes"] if meme_source_stats else 0
    source_memes_sent = meme_source_stats["nmemes_sent"] if meme_source_stats else 0
    source_memes_sent_events = (
        meme_source_stats["nmemes_sent_events"] if meme_source_stats else 0
    )
    source_memes_parsed = meme_source_stats["nmemes_parsed"] if meme_source_stats else 0

    published_at = meme.get("published_at")
    published_line = ""
    if isinstance(published_at, datetime):
        age_text = format_age(published_at)
        published_line = f"added {age_text} ago"

    source_url = meme_source.get("url") if meme_source else None
    source_url_text = source_url or "—"

    info_lines = [
        f"#{meme_id}",
        f"{meme_nlikes} 👍 {meme_ndislikes} 👎  {meme_views} 👁️",
    ]

    if published_line:
        info_lines.append(published_line)

    valid_sent_ratio = (
        int(source_memes_sent / source_memes_parsed * 100)
        if source_memes_parsed
        else 0
    )

    info_lines.extend(
        [
            "",
            f"source: {source_url_text}",
            f"{source_nlikes} 👍 {source_ndislikes} 👎",
            f"{source_memes_sent_events} 👁️ / {source_memes_sent} memes ({valid_sent_ratio}% valid)",  # noqa: E501
        ]
    )

    info_text = "\n".join(info_lines)

    await message.reply_text(
        info_text,
        disable_web_page_preview=True,
        **reply_kwargs,
    )
    return True


def get_meme_language_selector_keyboard(upload_id: int) -> list[list[dict]]:
    all_lang_buttons = []
    for lang, lang_text in SUPPORTED_LANGUAGES.items():
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


async def handle_message_with_meme(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """When a user sends a message with a meme"""
    message = update.message
    if not message:
        return

    if was_forwarded_from_bot(message, context.bot.id):
        meme_id = extract_meme_id_from_message(message)
        if meme_id is not None:
            handled = await _reply_with_forwarded_meme_stats(update, meme_id)
            if handled:
                return

    if update.effective_chat and update.effective_chat.type != ChatType.PRIVATE:
        return

    user = await get_user_info(update.effective_user.id)
    if not UserType(user["type"]).is_moderator:
        if user["nmemes_sent"] < 10:
            return await message.reply_text(
                localizer.t("upload.watch_memes_to_unblock_upload", user["interface_lang"]),
            )

        uploaded_today = await count_24h_uploaded_not_approved_memes(update.effective_user.id)
        if uploaded_today >= 5:
            return await message.reply_text(
                """
You already uploaded lots of memes today. Try again tomorrow.
Think about quality, not quantity: your goal is to get as many likes as possible.
Analyse your /uploads
                """
            )

    meme_upload = await create_meme_raw_upload(message)

    if not await check_if_user_follows_related_channel(
        context.bot, update.effective_user.id, user["interface_lang"]
    ):
        return await message.reply_text(
            f"""
You need to follow our channel to upload memes and try again:

{get_related_channel_link(user["interface_lang"])}
            """
        )

    reply_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    localizer.t("upload.rules_accept_button", user["interface_lang"]),
                    callback_data=RULES_ACCEPTED_CALLBACK_DATA_PATTERN.format(
                        upload_id=meme_upload["id"],
                    ),
                )
            ]
        ]
    )

    if update.message.photo:
        await update.message.reply_photo(
            photo=update.message.photo[-1].file_id,
            caption=localizer.t("upload.rules", user["interface_lang"]),
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
    elif update.message.video:
        await update.message.reply_video(
            video=update.message.video,
            caption=localizer.t("upload.rules", user["interface_lang"]),
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
    elif update.message.animation:
        await update.message.reply_animation(
            animation=update.message.animation,
            caption=localizer.t("upload.rules", user["interface_lang"]),
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
    else:
        raise Exception(f"not supported format: {update.message.to_json()}")


# callback: RULES_ACCEPTED_CALLBACK_DATA
async def handle_rules_accepted_callback(
    update: Update,
    _: ContextTypes.DEFAULT_TYPE,
) -> None:
    # user accepted the rules. Next, we need to ask to specify the language of a meme
    await update.callback_query.answer()
    user_info = await get_user_info(update.effective_user.id)

    upload_id = int(
        re.match(RULES_ACCEPTED_CALLBACK_DATA_REGEXP, update.callback_query.data).group(1)
    )

    await update.callback_query.message.edit_caption(
        localizer.t("upload.select_language", user_info["interface_lang"]),
        reply_markup=InlineKeyboardMarkup(get_meme_language_selector_keyboard(upload_id)),
        parse_mode=ParseMode.HTML,
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

    await log(f"""📥 Meme {meme["id"]} uploaded by #{update.effective_user.id}""", context.bot)

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
