"""
    Handle old callback queries from old bot version
"""


import random
from telegram import Update
from telegram.ext import (
    ContextTypes, 
)


from src.tgbot.service import (
    save_tg_user,
    save_user,
    add_user_language,
)

from src.tgbot.constants import Reaction
from src.recommendations.meme_queue import has_memes_in_queue
from src.tgbot.senders.next_message import next_message
from src.tgbot.senders.keyboards import queue_empty_alert_keyboard
from src.tgbot.constants import LOADING_EMOJIS


async def handle_empty_meme_queue_alert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if await has_memes_in_queue(user_id):
        return await next_message(user_id, Reaction.DISLIKE, update)
    
    emoji = random.choice(LOADING_EMOJIS)
    await update.message.edit_reply_markup(
        reply_markup=queue_empty_alert_keyboard(emoji),
    )
