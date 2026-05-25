"""
Handle old callback queries from old bot version
"""

from telegram import Update
from telegram.ext import (
    ContextTypes,
)

from src import localizer
from src.tgbot.exceptions import UserNotFound
from src.tgbot.user_info import get_user_info


async def _get_interface_lang(update: Update) -> str | None:
    if update.effective_user is None:
        return None

    try:
        user_info = await get_user_info(update.effective_user.id)
    except UserNotFound:
        return update.effective_user.language_code

    return user_info["interface_lang"] or update.effective_user.language_code


async def handle_broken_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import sys

    cb = update.callback_query.data if update.callback_query else "none"
    sys.stderr.write(f"[broken] catch-all fired: cb={cb}\n")
    sys.stderr.flush()
    lang = await _get_interface_lang(update)
    await update.effective_user.send_message(localizer.t("service.bot_updated", lang))
