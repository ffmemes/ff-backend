"""
    Handle old callback queries from old bot version
"""

import random

from telegram import Update
from telegram.ext import (
    ContextTypes,
)

from src.recommendations.meme_queue import check_queue, has_memes_in_queue
from src.tgbot.constants import LOADING_EMOJIS
from src.tgbot.logs import log
from src.tgbot.senders.keyboards import queue_empty_alert_keyboard
from src.tgbot.senders.next_message import next_message


async def handle_empty_meme_queue_alert(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    emoji = random.choice(LOADING_EMOJIS)
    await update.callback_query.answer(emoji)

    user_id = update.effective_user.id
    if await has_memes_in_queue(user_id):
        await update.callback_query.message.delete()
        return await next_message(user_id, update, prev_reaction_id=None)

    emoji = random.choice(LOADING_EMOJIS)
    await update.callback_query.message.edit_reply_markup(
        reply_markup=queue_empty_alert_keyboard(emoji),
    )
    await log(f"user_id: {user_id} has empty meme queue.")

    # Not sure if that's a good idea, a generation should be alraedy triggered.
    await check_queue(user_id)
