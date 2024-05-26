from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes,
)

from src.stats.user import calculate_inviter_stats, calculate_user_stats
from src.tgbot.constants import UserType
from src.tgbot.handlers.admin.service import delete_user, get_user_by_tg_username
from src.tgbot.handlers.stats.stats import get_user_stats_report
from src.tgbot.user_info import get_user_info, update_user_info_cache


async def handle_show_user_info(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Sends you the meme by it's id"""
    user = await get_user_info(update.effective_user.id)
    if user["type"] != UserType.ADMIN:
        return

    username = update.message.text[1:].strip().lower()
    selected_user = await get_user_by_tg_username(username)
    if selected_user is None:
        await update.message.reply_text(f"🚫 User @{username} not found.")
        return

    selected_user_info = await update_user_info_cache(selected_user["id"])

    # TODO: create a function which creates a user info string
    await calculate_user_stats()  # regenerate user stats
    await calculate_inviter_stats()

    report = await get_user_stats_report(selected_user_info["id"])

    await update.message.reply_text(
        f"""
ℹ️ <b>@{username}</b>
type: {selected_user_info["type"]}
{report}
        """,
        parse_mode=ParseMode.HTML,
    )


async def delete_user_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Deletes all user data we have for testing purposes"""
    user = await get_user_info(update.effective_user.id)
    if user["type"] != UserType.ADMIN:
        return

    # TODO: "are you sure" button + callback
    await delete_user(update.effective_user.id)
    await update.message.reply_text("Ciao 👋")
