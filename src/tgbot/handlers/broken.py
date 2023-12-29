"""
    Handle old callback queries from old bot version
"""


import logging
from telegram import Update
from telegram.ext import (
    ContextTypes, 
)


from src.tgbot.service import (
    save_tg_user,
    save_user,
    add_user_language,
)


async def handle_broken_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_user.send_message("The bot was updated. Please press /start to continue.")