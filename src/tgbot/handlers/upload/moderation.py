import asyncio
import logging
import re
from datetime import datetime
from typing import Any

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from src import localizer
from src.config import settings
from src.flows.storage.describe_memes import describe_single_meme
from src.flows.storage.memes import (
    add_watermark_to_meme_content,
    upload_meme_content_to_tg,
)
from src.recommendations.service import create_user_meme_reaction
from src.stats.meme import calculate_meme_reactions_and_engagement
from src.stats.meme_source import calculate_meme_source_stats
from src.storage.constants import MemeStatus, MemeType
from src.storage.service import find_meme_duplicate, update_meme
from src.storage.upload import download_meme_content_from_tg
from src.tgbot.constants import UserType
from src.tgbot.handlers.treasury.constants import TrxType
from src.tgbot.handlers.treasury.payments import pay_if_not_paid_with_alert
from src.tgbot.handlers.upload.constants import SUPPORTED_LANGUAGES
from src.tgbot.handlers.upload.service import (
    get_meme_raw_upload_by_id,
    update_meme_by_upload_id,
)
from src.tgbot.service import get_tg_user_by_id
from src.tgbot.user_info import get_user_info

UPLOADED_MEME_REIVIEW_CALLBACK_DATA_PATTERN = "upload:{upload_id}:review:{action}"
UPLOADED_MEME_REVIEW_CALLBACK_DATA_REGEXP = r"upload:(\d+):review:(\w+)"

LEADERBOARD_URL = (
    "https://metabase.okhlopkov.com/public/question/663c4def-4b42-4303-aa3b-73ab5bfa677a"
)


async def _notify_uploader(
    bot: Bot,
    meme_upload: dict[str, Any],
    text: str,
    parse_mode: str | None = ParseMode.HTML,
) -> None:
    """Send text to uploader, falling back to non-reply if original message was deleted."""
    try:
        await bot.send_message(
            chat_id=meme_upload["user_id"],
            reply_to_message_id=meme_upload["message_id"],
            text=text,
            parse_mode=parse_mode,
        )
    except Forbidden:
        logging.warning(f"Can't notify uploader #{meme_upload['user_id']}: blocked bot")
    except BadRequest:
        try:
            await bot.send_message(
                chat_id=meme_upload["user_id"],
                text=text,
                parse_mode=parse_mode,
            )
        except Forbidden:
            logging.warning(f"Can't notify uploader #{meme_upload['user_id']}: blocked bot")


async def _get_uploader_lang(user_id: int) -> str | None:
    user = await get_user_info(user_id)
    return user["interface_lang"] if user else None


async def _check_duplicate_via_ocr(meme: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    """Describe the meme inline via OpenRouter vision and check for OCR-text duplicates.

    Why: describe_memes cron is intentionally slow; for uploads we can't wait — run it synchronously
    so the uploader gets immediate feedback and the moderator queue stays clean of dupes.
    Non-images skip describe (OCR is image-only).
    Failures (rate limit, model errors, short text) fall through silently — manual review kicks in.

    Returns: (refreshed_meme, duplicate_of_id or None).
    """
    if meme["type"] != MemeType.IMAGE:
        return meme, None

    describe_log = logging.getLogger(__name__)
    try:
        status = await describe_single_meme(meme, describe_log)
    except Exception as e:
        logging.warning(f"Inline describe failed for meme {meme['id']}: {e}")
        return meme, None

    if isinstance(status, tuple):
        status = status[0]
    if status != "ok":
        return meme, None

    from src.tgbot.service import get_meme_by_id

    refreshed = await get_meme_by_id(meme["id"])
    if not refreshed:
        return meme, None

    ocr_text = (refreshed.get("ocr_result") or {}).get("text") or ""
    if len(ocr_text) < 12:
        return refreshed, None

    dup_id = await find_meme_duplicate(refreshed["id"], ocr_text)
    return refreshed, dup_id


async def uploaded_meme_auto_review(
    meme: dict[str, Any], meme_upload: dict[str, Any], bot: Bot
) -> None:
    uploader_lang = await _get_uploader_lang(meme_upload["user_id"])

    logging.info(f"Downloading meme {meme['id']} content")
    image_bytes = await download_meme_content_from_tg(meme["telegram_file_id"])

    logging.info(f"Adding watermark to meme {meme['id']} content")
    watermarked_meme_content = await add_watermark_to_meme_content(image_bytes, meme["type"])
    if watermarked_meme_content is None:
        return await _notify_uploader(
            bot, meme_upload, localizer.t("upload.watermark_failed", uploader_lang)
        )

    logging.info(f"Uploading watermarked meme {meme['id']} content to Telegram")
    meme = await upload_meme_content_to_tg(meme, watermarked_meme_content)
    if meme is None:
        return await _notify_uploader(
            bot, meme_upload, localizer.t("upload.tg_upload_failed", uploader_lang)
        )

    logging.info(f"Updating meme {meme['id']} status to WAITING_REVIEW")
    meme = await update_meme(
        meme["id"],
        status=MemeStatus.WAITING_REVIEW,
    )

    # Inline OCR + trigram dedup. Auto-reject on duplicate, else fall through to manual review.
    meme, duplicate_of = await _check_duplicate_via_ocr(meme)
    if duplicate_of is not None:
        logging.info(f"Meme {meme['id']} is a duplicate of {duplicate_of}, auto-rejecting")
        await update_meme(
            meme["id"],
            status=MemeStatus.DUPLICATE,
            duplicate_of=duplicate_of,
        )
        # Credit the uploader with a like on the original, so it counts as engagement
        await create_user_meme_reaction(
            meme_upload["user_id"],
            duplicate_of,
            "uploaded_meme",
            reaction_id=1,
            reacted_at=datetime.utcnow(),
        )
        return await _notify_uploader(
            bot, meme_upload, localizer.t("upload.rejected_duplicate", uploader_lang)
        )

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


def _tg_user_info_to_name(tg_user_info: dict):
    if tg_user_info.get("username"):
        return "@" + tg_user_info["username"]

    if tg_user_info.get("last_name"):
        return tg_user_info["first_name"] + " " + tg_user_info["last_name"]

    return tg_user_info["first_name"]


async def send_uploaded_meme_to_manual_review(
    meme: dict[str, Any],
    meme_upload: dict[str, Any],
    bot: Bot,
) -> None:
    tg_user_info = await get_tg_user_by_id(meme_upload["user_id"])
    name = _tg_user_info_to_name(tg_user_info)
    meme_lang = SUPPORTED_LANGUAGES.get(meme["language_code"]) or meme["language_code"]
    text = f"""
👨‍✈️ REVIEW MEME #{meme["id"]}
<b>Uploaded by</b>: {name} {tg_user_info["language_code"]}
<b>Meme language</b>: {meme_lang}
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

    if meme["type"] == MemeType.IMAGE:
        await bot.send_photo(
            chat_id=settings.UPLOADED_MEMES_REVIEW_CHAT_ID,
            photo=meme["telegram_file_id"],
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=review_keyboard(meme_upload["id"]),
        )
    elif meme["type"] in (MemeType.VIDEO, MemeType.ANIMATION):
        await bot.send_video(
            chat_id=settings.UPLOADED_MEMES_REVIEW_CHAT_ID,
            video=meme["telegram_file_id"],
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=review_keyboard(meme_upload["id"]),
        )


async def handle_uploaded_meme_review_button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    user = await get_user_info(update.effective_user.id)
    if not UserType(user["type"]).is_moderator:
        await update.callback_query.answer("You are not allowed to review memes")
        return

    await update.callback_query.answer()

    reg = re.match(UPLOADED_MEME_REVIEW_CALLBACK_DATA_REGEXP, update.callback_query.data)
    upload_id, action = int(reg.group(1)), reg.group(2)
    meme_upload = await get_meme_raw_upload_by_id(upload_id)
    prev_caption = update.callback_query.message.caption

    if meme_upload["user_id"] == update.effective_user.id:
        await update.callback_query.answer("You can't review your own memes")
        return

    meme = await update_meme_by_upload_id(
        upload_id,
        status=MemeStatus.OK if action == "approve" else MemeStatus.REJECTED,
    )

    await pay_if_not_paid_with_alert(
        context.bot,
        update.effective_user.id,
        TrxType.MEME_UPLOAD_REVIEWER,
        external_id=str(meme["id"]),
    )

    if action == "approve":
        new_caption = prev_caption + "\n✅ Approved by {}".format(update.effective_user.name)
        if (
            update.callback_query.message.caption != new_caption
            or update.callback_query.message.reply_markup is not None
        ):
            try:
                await update.callback_query.message.edit_caption(
                    caption=new_caption,
                    reply_markup=None,
                )
            except BadRequest as exc:
                if "Message is not modified" not in str(exc):
                    raise

        await create_user_meme_reaction(  # author auto like for the uploaded meme
            meme_upload["user_id"],
            meme["id"],
            "uploaded_meme",
            reaction_id=1,
            reacted_at=datetime.utcnow(),
        )

        await create_user_meme_reaction(  # moderator auto like for the uploaded meme
            update.effective_user.id,
            meme["id"],
            "uploaded_meme",
            reaction_id=1,
            reacted_at=datetime.utcnow(),
        )

        asyncio.create_task(calculate_meme_source_stats())
        asyncio.create_task(calculate_meme_reactions_and_engagement())

        await pay_if_not_paid_with_alert(
            context.bot,
            meme_upload["user_id"],
            TrxType.MEME_UPLOADER,
            external_id=str(meme["id"]),
        )

        uploader_lang = await _get_uploader_lang(meme_upload["user_id"])
        await _notify_uploader(
            context.bot, meme_upload, localizer.t("upload.approved", uploader_lang)
        )

    else:
        await update_meme_by_upload_id(upload_id, status=MemeStatus.REJECTED)
        new_caption = prev_caption + "\n❌ Rejected by {}".format(update.effective_user.name)
        if (
            update.callback_query.message.caption != new_caption
            or update.callback_query.message.reply_markup is not None
        ):
            try:
                await update.callback_query.message.edit_caption(
                    caption=new_caption,
                    reply_markup=None,
                )
            except BadRequest as exc:
                if "Message is not modified" not in str(exc):
                    raise

        uploader_lang = await _get_uploader_lang(meme_upload["user_id"])
        await _notify_uploader(
            context.bot, meme_upload, localizer.t("upload.rejected", uploader_lang)
        )
