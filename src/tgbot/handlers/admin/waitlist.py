from telegram import Update
from telegram.ext import (
    ContextTypes,
)

from src import localizer
from src.tgbot.bot import bot
from src.tgbot.constants import UserType
from src.tgbot.logs import log
from src.tgbot.service import get_user_by_tg_username, update_user
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

    await update_user(user_to_invite["id"], type=UserType.USER)
    invited_user_info = await update_user_info_cache(user_to_invite["id"])
    await log(f"👤 User {username} was invited by 👑{update.effective_user.name}")
    await bot.send_message(
        chat_id=user_to_invite["id"],
        text=localizer.t(
            "onboarding.invited_by_admin", invited_user_info["interface_lang"]
        ),
    )
    await update.message.reply_text(f"✅ You invited @{username}.")
