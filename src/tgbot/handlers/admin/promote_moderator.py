from collections.abc import Mapping

import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from src.tgbot.constants import TELEGRAM_MODERATOR_CHAT_ID, UserType
from src.tgbot.handlers.admin.service import get_user_by_tg_username
from src.tgbot.service import (
    add_user_tg_chat_membership,
    get_user_by_id,
    update_user,
)
from src.tgbot.user_info import update_user_info_cache


async def _is_admin(user_info: Mapping[str, object] | None) -> bool:
    if not user_info:
        return False

    raw_type = user_info.get("type")
    try:
        return UserType(str(raw_type)) == UserType.ADMIN
    except ValueError:
        logging.warning("Unknown user type '%s' encountered during admin check", raw_type)
        return False


async def handle_promote_moderator(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    if message is None or message.text is None:
        return

    requester = await get_user_by_id(message.from_user.id)
    if not await _is_admin(requester):
        await message.reply_text("🚫 Only admins can promote moderators.")
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text("Usage: /promotemod <telegram_id|@username>")
        return

    identifier = parts[1].strip()
    target = None

    if identifier.startswith("@"):  # username lookup
        username = identifier[1:]
        if not username:
            await message.reply_text("🚫 Please provide a valid username after @.")
            return
        target = await get_user_by_tg_username(username)
    else:
        try:
            telegram_id = int(identifier)
        except ValueError:
            await message.reply_text(
                "🚫 Identifier must be a Telegram ID or @username."
            )
            return
        target = await get_user_by_id(telegram_id)

    if target is None:
        await message.reply_text("🚫 Could not find the specified user.")
        return

    target_id = int(target["id"])

    try:
        invite_link = await context.bot.create_chat_invite_link(
            chat_id=TELEGRAM_MODERATOR_CHAT_ID,
            creates_join_request=False,
            member_limit=1,
        )
    except TelegramError:
        logging.exception("Failed to generate moderator invite link for user_id=%s", target_id)
        await message.reply_text("❌ Failed to generate invite link. Try again later.")
        return

    await update_user(target_id, type=UserType.MODERATOR.value)
    await add_user_tg_chat_membership(target_id, TELEGRAM_MODERATOR_CHAT_ID)
    await update_user_info_cache(target_id)

    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                "🎉 You have been promoted to moderator! "
                f"Here is your invite link: {invite_link.invite_link}"
            ),
            disable_web_page_preview=True,
        )
    except TelegramError:
        logging.exception("Failed to send moderator invite to user_id=%s", target_id)
        await message.reply_text(
            "⚠️ Promotion updated, but sending the invite link failed."
        )
        return

    await message.reply_text("✅ User promoted to moderator and invite link sent.")
