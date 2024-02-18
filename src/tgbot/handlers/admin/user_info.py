from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes,
)

from src.stats.service import get_user_stats
from src.stats.user import calculate_user_stats
from src.tgbot.constants import UserType
from src.tgbot.service import get_user_by_tg_username
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

    await calculate_user_stats()  # regenerate user stats
    user_stats = await get_user_stats(selected_user["id"])

    report = ""
    for k, v in user_stats.items():
        report += f"<b>{k}</b>: {v}\n"

    await update.message.reply_text(
        f"""
ℹ️ <b>@{username}</b>
type: {selected_user_info["type"]}
{report}
        """,
        parse_mode=ParseMode.HTML,
    )
