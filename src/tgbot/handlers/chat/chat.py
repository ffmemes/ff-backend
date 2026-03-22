import logging
import random

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from src.config import settings
from src.tgbot.handlers.chat.reaction import give_random_reaction
from src.tgbot.handlers.chat.service import (
    get_latest_chat_messages,
    save_telegram_message,
)
from src.tgbot.handlers.chat.utils import _reply_and_delete
from src.tgbot.handlers.treasury.constants import PAYOUTS, TrxType
from src.tgbot.handlers.treasury.payments import charge_user
from src.tgbot.handlers.treasury.service import (
    check_if_treasury_trx_exists,
    get_user_balance,
)

logger = logging.getLogger(__name__)


def is_bot_mentioned(msg: Message, bot_id: int, bot_username: str) -> bool:
    """Check if the bot was mentioned or replied to."""
    if msg.text and f"@{bot_username.lower()}" in msg.text.lower():
        return True

    if msg.reply_to_message and msg.reply_to_message.from_user:
        if msg.reply_to_message.from_user.id == bot_id:
            return True

    return False


async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all group messages: persist, detect triggers, run agent or react."""
    msg = update.message
    if not msg:
        return

    # Persist all group messages for AI context
    try:
        await save_telegram_message(msg)
    except Exception as e:
        logger.warning("Failed to save message: %s", e)

    # Check if chat agent is enabled
    if not settings.CHAT_AGENT_ENABLED:
        if random.random() < 0.05:
            await give_random_reaction(update, context)
        return

    bot_id = context.bot.id
    bot_username = context.bot.username or settings.TELEGRAM_BOT_USERNAME or ""

    # Check if bot was mentioned or replied to
    if is_bot_mentioned(msg, bot_id, bot_username):
        return await handle_agent_trigger(update, context)

    # Random reaction (5% chance, free)
    if random.random() < 0.05:
        await give_random_reaction(update, context)


async def handle_agent_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle a direct mention/reply trigger — charge 1 burger and run agent."""
    if not update.effective_user:
        return
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    msg = update.message

    # Check balance
    balance = await get_user_balance(user_id)
    cost = PAYOUTS[TrxType.BOT_REPLY_PAYMENT] * (-1)  # 1

    if balance < cost:
        text = "У меня есть мемы на любой вкус, но сначала нужны бургеры 🍔"
        return await _reply_and_delete(
            msg,
            text,
            sleep_sec=10,
            delete_original=False,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "Получить 🍔🍔🍔",
                            url="https://t.me/ffmemesbot?start=kitchen",
                        )
                    ]
                ]
            ),
        )

    # Charge 1 burger (idempotent — prevents double-charge on webhook retry)
    external_id = f"chat_agent:{chat_id}:{msg.message_id}"
    if await check_if_treasury_trx_exists(user_id, TrxType.BOT_REPLY_PAYMENT, external_id):
        return  # Already charged for this message
    await charge_user(
        user_id,
        TrxType.BOT_REPLY_PAYMENT,
        external_id=external_id,
    )

    # Show typing indicator
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    except (BadRequest, Forbidden):
        return

    # Run the agent
    try:
        from src.tgbot.handlers.chat.agent.runner import run_chat_agent

        response = await run_chat_agent(
            bot=context.bot,
            chat_id=chat_id,
            user_id=user_id,
            reply_to_message_id=msg.message_id,
        )

        if response:
            sent_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=response,
                reply_to_message_id=msg.message_id,
            )
            await save_telegram_message(sent_msg)
        else:
            # Agent returned None (API down, max turns, etc.) — send fallback
            await _send_fallback_meme(context.bot, chat_id, msg.message_id)
    except Exception as e:
        logger.error("Agent error in chat %s: %s", chat_id, e, exc_info=True)
        try:
            await _send_fallback_meme(context.bot, chat_id, msg.message_id)
        except Exception:
            pass


async def _send_fallback_meme(bot: Bot, chat_id: int, reply_to_message_id: int):
    """Send a random popular meme as fallback when the agent fails."""
    from sqlalchemy import text as sql_text

    from src.database import fetch_one

    row = await fetch_one(sql_text("""
        SELECT m.id, m.type, m.telegram_file_id
        FROM meme m
        INNER JOIN meme_stats ms ON ms.meme_id = m.id
        WHERE m.status = 'ok'
          AND m.telegram_file_id IS NOT NULL
          AND ms.nlikes > 10
        ORDER BY random()
        LIMIT 1
    """))

    if not row:
        return

    from src.tgbot.handlers.chat.group_meme_reaction import build_meme_reaction_keyboard
    keyboard = build_meme_reaction_keyboard(row["id"])

    file_id = row["telegram_file_id"]
    if row["type"] == "animation":
        await bot.send_animation(chat_id=chat_id, animation=file_id, reply_markup=keyboard, reply_to_message_id=reply_to_message_id)
    elif row["type"] == "video":
        await bot.send_video(chat_id=chat_id, video=file_id, reply_markup=keyboard, reply_to_message_id=reply_to_message_id)
    else:
        await bot.send_photo(chat_id=chat_id, photo=file_id, reply_markup=keyboard, reply_to_message_id=reply_to_message_id)
