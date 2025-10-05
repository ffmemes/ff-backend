from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes,
)

from src.stats.user import calculate_inviter_stats, calculate_user_stats
from src.tgbot.constants import UserType
from src.tgbot.handlers.admin.service import delete_user, get_user_by_tg_username
from src.tgbot.handlers.stats.stats import get_user_stats_report
from src.tgbot.handlers.treasury.service import get_user_balance
from src.tgbot.user_info import get_user_info, update_user_info_cache

DELETE_USER_DATA_CONFIRMATION_CALLBACK = "user_delete_confirm"


async def handle_show_user_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_chat_action(
        chat_id=update.effective_user.id,
        action="typing",
    )

    """Sends you the meme by it's id"""
    user = await get_user_info(update.effective_user.id)
    if user["type"] != UserType.ADMIN:
        return

    username = update.message.text[1:].strip().lower()
    selected_user = await get_user_by_tg_username(username)
    if selected_user is None:
        await update.message.reply_text(f"🚫 User @{username} not found.")
        return

    # TODO: create a function which creates a user info string
    await calculate_user_stats()  # regenerate user stats
    await calculate_inviter_stats()
    balance = await get_user_balance(selected_user["id"])

    selected_user_info = await update_user_info_cache(selected_user["id"])
    report = await get_user_stats_report(selected_user["id"])

    await update.message.reply_text(
        f"""
ℹ️ <b>@{username}</b>
type: {selected_user_info["type"]}
balance: {balance} 🍔
{report}
        """,
        parse_mode=ParseMode.HTML,
    )


async def delete_user_data_confirmation_page(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    name = update.effective_user.name
    await update.message.reply_text(
        f"Going to erase all data about {name}. \n\nAre you sure?",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Delete everything",
                        callback_data=DELETE_USER_DATA_CONFIRMATION_CALLBACK,
                    )
                ]
            ]
        ),
    )


async def delete_user_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Deletes all user data we have for testing purposes"""
    # user = await get_user_info(update.effective_user.id)
    # if user["type"] != UserType.ADMIN:
    #     return

    # TODO: "are you sure" button + callback
    await delete_user(update.effective_user.id)
    await update.effective_user.send_message("Ciao 👋\n\n --> press /start to try again 👾")
