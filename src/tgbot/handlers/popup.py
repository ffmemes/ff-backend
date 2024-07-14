"""
    Handle reactions on sent memes
"""
import asyncio

from telegram import Update
from telegram.ext import (
    ContextTypes,
)

from src.recommendations.service import update_user_last_active_at
from src.tgbot.senders.next_message import next_message
from src.tgbot.service import update_user_popup_log


async def handle_popup_button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    user_id = update.effective_user.id
    popup_id = update.callback_query.data[2:]
    reaction_is_new = await update_user_popup_log(user_id, popup_id)

    asyncio.create_task(update_user_last_active_at(user_id))

    if reaction_is_new:
        return await next_message(
            context.bot,
            user_id,
            prev_update=update,
            prev_reaction_id=None,
        )
