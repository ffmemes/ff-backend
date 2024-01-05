"""
    Handle reactions on sent memes
"""


import logging
from telegram import Update
from telegram.ext import (
    ContextTypes, 
)


from src.tgbot.senders.meme import send_meme
from src.tgbot.senders.alerts import send_queue_preparing_alert
from src.recommendations.service import (
    update_user_meme_reaction, 
)

from src.recommendations.meme_queue import get_next_meme_for_user


async def handle_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    meme_id, reaction_id = update.callback_query.data[2:].split(":")

    # TODO background task?
    reaction_is_new = await update_user_meme_reaction(
        user_id=user_id,
        meme_id=int(meme_id),
        reaction_id=int(reaction_id),
    )
    if not reaction_is_new:
        # TODO: remove this debug logging
        logging.info(f"User {user_id} already reacted to meme {meme_id}")
        return

    meme_to_send = await get_next_meme_for_user(user_id)
    if meme_to_send:
        await send_meme(user_id, meme_to_send)
        return
    
    await send_queue_preparing_alert(user_id)
    
    # no memes in queue
    # TODO: send a message that we are working on it
    

