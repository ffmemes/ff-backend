import asyncio
import logging
import re
from datetime import datetime
from typing import Any

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from src.config import settings
from src.flows.storage.memes import (
    add_watermark_to_meme_content,
    ocr_meme_content,
    upload_meme_content_to_tg,
)
from src.recommendations.service import create_user_meme_reaction
from src.stats.meme import calculate_meme_reactions_stats
from src.stats.meme_source import calculate_meme_source_stats
from src.storage.constants import MemeStatus
from src.storage.service import (
    find_meme_duplicate,
    update_meme,
)
from src.storage.upload import download_meme_content_from_tg
from src.tgbot.constants import UserType
from src.tgbot.handlers.upload.service import (
    get_meme_raw_upload_by_id,
    update_meme_by_upload_id,
)
from src.tgbot.user_info import get_user_info

UPLOADED_MEME_REIVIEW_CALLBACK_DATA_PATTERN = "upload:{upload_id}:review:{action}"
UPLOADED_MEME_REVIEW_CALLBACK_DATA_REGEXP = r"upload:(\d+):review:(\w+)"

LEADERBOARD_URL = "https://metabase.okhlopkov.com/public/question/663c4def-4b42-4303-aa3b-73ab5bfa677a"


async def uploaded_meme_auto_review(
    meme: dict[str, Any], meme_upload: dict[str, Any], bot: Bot
) -> None:
    logging.info(f"Downloading meme {meme['id']} content")
    image_bytes = await download_meme_content_from_tg(meme["telegram_file_id"])

    logging.info(f"OCR meme {meme['id']} content")
    meme = await ocr_meme_content(
        meme["id"],
        image_bytes,
        meme["language_code"],
    )
    if meme is None:
        return await bot.send_message(
            chat_id=meme_upload["user_id"],
            reply_to_message_id=meme_upload["message_id"],
            text="""
❌ MEME REJECTED:
Something went wrong when we tried read text on your meme. Just try again.
            """,
        )

    logging.info(f"Adding watermark to meme {meme['id']} content")
    watermarked_meme_content = await add_watermark_to_meme_content(
        image_bytes, meme["type"]
    )
    if watermarked_meme_content is None:
        return await bot.send_message(
            chat_id=meme_upload["user_id"],
            reply_to_message_id=meme_upload["message_id"],
            text="""
❌ MEME REJECTED:
Something went wrong when we tried to add watermark to your meme. Just try again.
            """,
        )

    logging.info(f"Uploading watermarked meme {meme['id']} content to Telegram")
    meme = await upload_meme_content_to_tg(meme, watermarked_meme_content)
    if meme is None:
        return await bot.send_message(
            chat_id=meme_upload["user_id"],
            reply_to_message_id=meme_upload["message_id"],
            text="""
❌ MEME REJECTED:
Something went wrong when we tried to upload your meme to Telegram. Just try again.
            """,
        )

    logging.info(f"Finding duplicates of meme {meme['id']}")
    duplicate_meme_id = await find_meme_duplicate(
        meme["id"],
        meme["ocr_result"]["text"],
    )
    if duplicate_meme_id:
        await update_meme(
            meme["id"],
            status=MemeStatus.DUPLICATE,
            duplicate_of=duplicate_meme_id,
        )

        # set like for the uploaded meme
        await create_user_meme_reaction(
            duplicate_meme_id,
            meme["id"],
            "uploaded_meme",
            reaction_id=1,
            reacted_at=datetime.utcnow(),
        )

        return await bot.send_message(
            chat_id=meme_upload["user_id"],
            reply_to_message_id=meme_upload["message_id"],
            text="""
❌ MEME REJECTED:
Somebody already submitted this meme, sorry... Try another one.
            """,
        )

    logging.info(f"Updating meme {meme['id']} status to WAITING_REVIEW")
    meme = await update_meme(
        meme["id"],
        status=MemeStatus.WAITING_REVIEW,
    )

    # send meme to a manual review
    return await send_uploaded_meme_to_manual_review(meme, meme_upload, bot)


def review_keyboard(upload_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Approve",
                    callback_data=UPLOADED_MEME_REIVIEW_CALLBACK_DATA_PATTERN.format(
                        upload_id=upload_id, action="approve"
                    ),
                ),
                InlineKeyboardButton(
                    text="❌ Reject",
                    callback_data=UPLOADED_MEME_REIVIEW_CALLBACK_DATA_PATTERN.format(
                        upload_id=upload_id, action="reject"
                    ),
                ),
            ],
        ],
    )


async def send_uploaded_meme_to_manual_review(
    meme: dict[str, Any],
    meme_upload: dict[str, Any],
    bot: Bot,
) -> None:
    text = f"""
👨‍✈️ REVIEW MEME #{meme["id"]}
<b>Upload Id</b>: {meme_upload["id"]}
<b>Uploaded by</b>: #{meme_upload["user_id"]}
<b>Language code</b>: {meme["language_code"]}
    """

    if meme_upload["forward_origin"]:
        fo = meme_upload["forward_origin"]
        forward_type = fo.get("type")
        if forward_type == "channel":
            username = fo.get("chat", {}).get("username")
            if username:
                text += f"\n<b>Forwarded from</b>: @{username}"

        if forward_type == "user":
            username = fo.get("sender_user", {}).get("username")
            if username:
                text += f"\n<b>Forwarded from</b>: @{username}"

    await bot.send_photo(
        chat_id=settings.UPLOADED_MEMES_REVIEW_CHAT_ID,
        photo=meme["telegram_file_id"],
        caption=text,
        parse_mode=ParseMode.HTML,
        reply_markup=review_keyboard(meme_upload["id"]),
    )


async def handle_uploaded_meme_review_button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    user = await get_user_info(update.effective_user.id)
    if user["type"] != UserType.ADMIN:
        await update.callback_query.answer("You are not allowed to review memes")
        return

    await update.callback_query.answer()

    reg = re.match(
        UPLOADED_MEME_REVIEW_CALLBACK_DATA_REGEXP, update.callback_query.data
    )
    upload_id, action = int(reg.group(1)), reg.group(2)
    meme_upload = await get_meme_raw_upload_by_id(upload_id)
    prev_caption = update.callback_query.message.caption

    if action == "approve":
        meme = await update_meme_by_upload_id(upload_id, status=MemeStatus.OK)
        await update.callback_query.message.edit_caption(
            caption=prev_caption
            + "\n✅ Approved by {}".format(update.effective_user.name),
            reply_markup=None,
        )

        await create_user_meme_reaction(
            meme_upload["user_id"],
            meme["id"],
            "uploaded_meme",
            reaction_id=1,
            reacted_at=datetime.utcnow(),
        )

        asyncio.create_task(calculate_meme_source_stats())
        asyncio.create_task(calculate_meme_reactions_stats())

        await context.bot.send_message(
            chat_id=meme_upload["user_id"],
            reply_to_message_id=meme_upload["message_id"],
            text=f"""
🎉🎉🎉

Your <b>meme has been approved</b> and soon bot will send it to other users!

You can see your meme #{meme["id"]} stats on <a href="{LEADERBOARD_URL}">LEADERBOARD</a>
            """,
            parse_mode=ParseMode.HTML,
        )

    else:
        await update_meme_by_upload_id(upload_id, status=MemeStatus.REJECTED)
        await update.callback_query.message.edit_caption(
            caption=prev_caption
            + "\n❌ Rejected by {}".format(update.effective_user.name),
            reply_markup=None,
        )
        await context.bot.send_message(
            chat_id=meme_upload["user_id"],
            reply_to_message_id=meme_upload["message_id"],
            text="""
😢😢😢

Your meme was rejected by our moderators. Send us something else!
            """,
        )
