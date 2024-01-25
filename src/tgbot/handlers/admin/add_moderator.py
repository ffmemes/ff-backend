"""
    Handle add moderator command
"""

from telegram import Update
from telegram.ext import (
    ContextTypes,
)
from src.tgbot.constants import UserType
from src.tgbot.logs import log

from src.tgbot.service import get_user_by_id, get_user_by_username, save_user


async def add_moderator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in :

    message_split = update.message.text.split()
    if len(message_split) < 2:
        await update.message.reply_text("Please specify a username/user_id")
        return
    parameter = message_split[1]

    if parameter.startswith("@"):
        parameter = parameter[1:]
        user = await get_user_by_username(parameter)
    elif parameter.isdigit():
        user = await get_user_by_id(int(parameter))
    await save_user(id=user["id"], type=UserType.MODERATOR)
    user_str = f"@{user['username']}" if user["username"] else f"#{user['id']}"
    admin_str = (
        f"@{update.effective_user.username}"
        if update.effective_user.username
        else f"#{update.effective_user.id}"
    )
    await log(f"User {user_str} has been promoted to moderator by {admin_str}")
