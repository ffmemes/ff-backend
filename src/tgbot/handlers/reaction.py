"""
    Handle reactions on sent memes
"""


import logging
from telegram import Update
from telegram.ext import (
    ContextTypes, 
)

from src.tgbot.senders.next_message import next_message
from src.recommendations.service import (
    update_user_meme_reaction, 
)


async def handle_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    meme_id, reaction_id = update.callback_query.data[2:].split(":")
    logging.info(f"🛜 reaction: user_id={user_id}, meme_id={meme_id}, reaction_id={reaction_id}")

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
    
    return await next_message(
        user_id, 
        prev_update=update,
        prev_reaction_id=int(reaction_id),
    )
