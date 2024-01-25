"""
    Handle /add_mod <new_moderator_user_id_or_username> admin command
"""

from telegram import Update
from telegram.ext import (
    ContextTypes,
)
from src.tgbot.constants import UserType
from src.tgbot.logs import log

from src.tgbot.service import get_tg_user_by_id, get_user_by_id, get_user_by_username, save_user, update_user
from src.tgbot.utils import format_user_to_str


async def handle_add_moderator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Promotes some user to moderator if the sender is admin"""
    user = await get_user_by_id(update.effective_user.id)
    if user["type"] != UserType.ADMIN:
        return

    message_split = update.message.text.split()
    if len(message_split) < 2:
        await update.message.reply_text("Please specify a username/user_id")
        return

    parameter = message_split[1]
    if parameter.isdigit():
        user_to_promote = await get_user_by_id(int(parameter))
    else:
        parameter = parameter[1:] if parameter.startswith("@") else parameter
        user_to_promote = await get_user_by_username(parameter)

    if user_to_promote is None:
        await update.message.reply_text(f"User with username/id={parameter} not found")
        return

    await update_user(id=user_to_promote["id"], type=UserType.MODERATOR)
    tg_user_to_promote = await get_tg_user_by_id(user_to_promote["id"])  # to get the new mod's username

    user_str = format_user_to_str(user_to_promote["id"], tg_user_to_promote["username"])
    admin_str = format_user_to_str(
        update.effective_user.id, update.effective_user.username
    )

    await update.message.reply_text(f"User {user_str} has been promoted to moderator")
    await log(f"User {user_str} has been set to moderator by {admin_str}")
