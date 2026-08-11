"""User-facing /help and /last (re-show previous meme)."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from src import localizer
from src.storage.schemas import MemeData
from src.tgbot.repo.memes import get_last_reacted_meme_for_user
from src.tgbot.senders.meme import send_meme_to_user
from src.tgbot.user_info import get_user_info

logger = logging.getLogger(__name__)


def _interface_lang(user_info: dict | None) -> str | None:
    if not user_info:
        return None
    return user_info.get("interface_lang")


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return

    try:
        user_info = await get_user_info(update.effective_user.id)
    except Exception:
        logger.exception("help: failed to load user_info for %s", update.effective_user.id)
        user_info = None

    text = localizer.t("help.text", _interface_lang(user_info))
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def handle_last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Re-send the user's most recently delivered meme (skip undo is out of scope)."""
    if update.effective_user is None or update.message is None:
        return

    user_id = update.effective_user.id
    try:
        user_info = await get_user_info(user_id)
    except Exception:
        logger.exception("last: failed to load user_info for %s", user_id)
        user_info = None

    lang = _interface_lang(user_info)
    row = await get_last_reacted_meme_for_user(user_id)
    if row is None:
        await update.message.reply_text(localizer.t("last.none", lang))
        return

    try:
        meme = MemeData(
            id=row["id"],
            type=row["type"],
            telegram_file_id=row["telegram_file_id"],
            caption=row.get("caption"),
            language_code=row.get("language_code"),
            recommended_by="last",
            nlikes=int(row.get("nlikes") or 0),
        )
    except Exception:
        logger.exception("last: invalid meme row for user %s: %s", user_id, row.get("id"))
        await update.message.reply_text(localizer.t("last.unavailable", lang))
        return

    try:
        await send_meme_to_user(
            context.bot,
            user_id,
            meme,
            recommended_by="last",
        )
    except Exception:
        logger.exception("last: failed to re-send meme %s to user %s", meme.id, user_id)
        await update.message.reply_text(localizer.t("last.unavailable", lang))
