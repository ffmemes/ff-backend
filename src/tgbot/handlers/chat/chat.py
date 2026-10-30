import logging
import random

from telegram import Update
from telegram.ext import ContextTypes

from src.stats.service import get_user_stats
from src.tgbot.constants import TELEGRAM_CHAT_RU_CHAT_ID
from src.tgbot.handlers.chat.mod_chat_stat import handle_mod_chat_meme_forward
from src.tgbot.handlers.chat.reaction import give_random_reaction
from src.tgbot.handlers.chat.service import (
    save_telegram_message,
)
from src.tgbot.handlers.chat.utils import _reply_and_delete

logger = logging.getLogger(__name__)

ANTISPAM_MIN_REACTIONS = 5
ANTISPAM_CHAT_IDS = {TELEGRAM_CHAT_RU_CHAT_ID}


async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all group messages: persist, mod-chat stats, anti-spam, random reactions."""
    msg = update.message
    if not msg:
        return

    # Persist all group messages
    try:
        await save_telegram_message(msg)
    except Exception as e:
        logger.error("Failed to save message: %s", e, exc_info=True)

    # Moderator chat: reply with short stats when a meme is forwarded here.
    try:
        if await handle_mod_chat_meme_forward(msg):
            return
    except Exception as e:
        logger.error("mod-chat stat reply error: %s", e, exc_info=True)

    # Skip bot messages, channel forwards (777000), and service messages
    if not msg.from_user or msg.from_user.is_bot or msg.from_user.id == 777000:
        return

    # Anti-spam: in protected chats, delete messages from users without enough reactions
    if msg.chat_id in ANTISPAM_CHAT_IDS:
        user_id = msg.from_user.id
        stats = await get_user_stats(user_id)
        total_reactions = (stats.get("nlikes", 0) + stats.get("ndislikes", 0)) if stats else 0
        if total_reactions < ANTISPAM_MIN_REACTIONS:
            await _reply_and_delete(
                msg,
                "Чтобы писать в чат, сначала воспользуйся ботом 👇\n"  # noqa: E501
                "https://t.me/ffmemesbot",
                sleep_sec=15,
                delete_original=True,
            )
            return

    # Random reaction (5% chance, free)
    if random.random() < 0.05:
        await give_random_reaction(update, context)
