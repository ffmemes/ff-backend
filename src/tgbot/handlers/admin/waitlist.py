import asyncio
from datetime import datetime

from telegram import Update
from telegram.error import Forbidden
from telegram.ext import (
    ContextTypes,
)

from src import localizer
from src.tgbot.bot import bot
from src.tgbot.constants import UserType
from src.tgbot.handlers.admin.service import (
    get_user_by_tg_username,
    get_waitlist_users_registered_before,
)
from src.tgbot.logs import log
from src.tgbot.service import update_user
from src.tgbot.user_info import get_user_info, update_user_info_cache


async def handle_waitlist_invite(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Sends you the meme by it's id"""
    user = await get_user_info(update.effective_user.id)
    if user["type"] != UserType.ADMIN:
        return

    message_split = update.message.text.split(" ")
    if len(message_split) < 2 or not message_split[1].startswith("@"):
        await update.message.reply_text("USAGE: /invite @username")
        return

    username = message_split[1][1:]
    user_to_invite = await get_user_by_tg_username(username)
    if user_to_invite is None:
        await update.message.reply_text(f"🚫 User @{username} not found.")
        return

    if user_to_invite["type"] != UserType.WAITLIST:
        await update.message.reply_text(f"🚫 User @{username} is not in waitlist.")
        return
    await invite_user(user_to_invite["id"])
    await update.message.reply_text(f"✅ You invited @{username}.")


async def handle_waitlist_invite_before(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Gives access to everyone, who registered before a certain date"""
    user = await get_user_info(update.effective_user.id)
    if user["type"] != UserType.ADMIN:
        return

    message_split = update.message.text.split(" ")
    if len(message_split) != 2:
        await update.message.reply_text(
            "USAGE: /invite_before yyyy-mm-dd\n"
            "Invites everyone registered before specified date."
        )
        return

    date_str = message_split[1]
    try:
        date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        await update.message.reply_text(
            "Invalid date format. Use /invite_before yyyy-mm-dd"
        )
        return

    # get all users registered that day
    users = await get_waitlist_users_registered_before(date)
    await update.message.reply_text(
        f"Inviting {len(users)} users registered before {date_str}."
    )
    await log(
        f"Inviting {len(users)} users registered before {date_str}.",
    )

    for i, user in enumerate(users):
        await invite_user(user["id"])
        await asyncio.sleep(0.2)
        if i % 50 == 0 and i != 0:
            await update.message.reply_text(
                f"⏳ Invited {i + 1}/{len(users)} users registered before {date_str}.",
            )

    await update.message.reply_text(
        f"✅ Invited {len(users)} users registered before {date_str}."
    )


async def invite_user(user_id: int) -> None:
    await update_user(user_id, type=UserType.USER)
    user_info = await update_user_info_cache(user_id)
    try:
        await bot.send_message(
            user_id,
            localizer.t("onboarding.invited_by_admin", user_info["interface_lang"]),
        )
    except Forbidden:
        await update_user(user_id, type=UserType.BLOCKED_BOT)
        await update_user_info_cache(user_id)
