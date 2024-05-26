from telegram import Update
from telegram.ext import (
    ContextTypes,
)

from src.tgbot.logs import log


async def handle_chat_boost(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.chat_boost.chat.id

    await log(
        f"🚀 User {update.effective_user.id} boosted chat {chat_id}.",
        context.bot,
    )

    # TODO: I don't know how to get user_id from the boost. Let's see the logs

    # give user 2 🍔
