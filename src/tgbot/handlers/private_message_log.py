"""Persist private DM traffic into message_tg.

Historically message_tg only stored group/channel messages for the chat agent.
Private slash commands (/last, /kitchen, …) were invisible in analytics.

Inbound private messages (text, media, commands) are now written with the same
row shape. Outbound bot messages are still not mirrored here — product ledgers
cover meme sends (user_meme_reaction) and other domains.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from src.tgbot.handlers.chat.service import save_telegram_message

logger = logging.getLogger(__name__)


async def log_private_inbound_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Best-effort: never block real command/upload handlers (PTB group -1)."""
    msg = update.message
    if msg is None:
        return
    try:
        await save_telegram_message(msg)
    except Exception:
        logger.warning(
            "Failed to log private message %s from user %s",
            getattr(msg, "message_id", None),
            getattr(update.effective_user, "id", None),
            exc_info=True,
        )
