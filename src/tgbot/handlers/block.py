"""
Handles user blocking / unblocking the bot.
"""

from telegram import Update
from telegram.ext import ContextTypes

from src.tgbot.logs import html_escape, log
from src.tgbot.service import mark_user_blocked, mark_user_unblocked


async def handle_user_blocked_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle my_chat_member MEMBER → KICKED in a private chat."""
    user_tg = update.my_chat_member.from_user
    user_id = user_tg.id

    if update.effective_chat.id != user_id:
        await log(
            f"user #{user_id} blocked us in chat_id: {update.effective_chat.id}",
            context.bot,
        )
        return

    updated = await mark_user_blocked(
        user_id=user_id,
        source="my_chat_member",
        when=update.my_chat_member.date,
    )
    if updated is None:
        return

    # Lightweight admin log: fields we already have, no stats recompute.
    message = (
        f"⛔️ <b>BLOCKED</b> by {html_escape(user_tg.name)} / #{user_id}\n"
        f"<b>registered</b>: {updated['created_at']}\n"
        f"<b>tg lang</b>: {html_escape(user_tg.language_code or '—')}\n"
        f"<b>nickname</b>: {html_escape(updated.get('nickname') or '—')}"
    )
    await log(message, context.bot)


async def handle_user_unblocked_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle my_chat_member KICKED → MEMBER in a private chat."""
    user_tg = update.my_chat_member.from_user
    user_id = user_tg.id

    if update.effective_chat.id != user_id:
        return

    await mark_user_unblocked(
        user_id=user_id,
        source="my_chat_member",
        when=update.my_chat_member.date,
    )
