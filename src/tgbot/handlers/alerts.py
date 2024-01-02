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

from src.recommendations.meme_queue import get_next_meme_for_user, has_memes_in_queue
from src.tgbot.senders.meme import send_meme
from src.tgbot.senders.keyboards import get_queue_empty_alert_keyboard
from src.tgbot.constants import LOADING_EMOJIS


async def handle_empty_meme_queue_alert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if await has_memes_in_queue(user_id):
        meme_to_send = await get_next_meme_for_user(user_id)
        if meme_to_send:
            return await send_meme(user_id, meme_to_send)
    
    emoji = random.choice(LOADING_EMOJIS)
    await update.message.edit_reply_markup(
        reply_markup=get_queue_empty_alert_keyboard(emoji),
    )