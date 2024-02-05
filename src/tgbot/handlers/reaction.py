"""
    Handle reactions on sent memes
"""

import logging

from telegram import Update
from telegram.ext import (
    ContextTypes,
)

from src.recommendations.service import (
    update_user_meme_reaction,
)
from src.tgbot.senders.next_message import next_message
from src.tgbot.user_info import update_user_info_counters


async def handle_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    meme_id, reaction_id = update.callback_query.data[2:].split(":")
    logging.info(
        f"🛜 reaction: user_id={user_id}, meme_id={meme_id}, reaction_id={reaction_id}"
    )

    await update_user_info_counters(user_id)

    reaction_is_new = await update_user_meme_reaction(
        user_id=user_id,
        meme_id=int(meme_id),
        reaction_id=int(reaction_id),
    )

    if reaction_is_new:
        return await next_message(
            user_id,
            prev_update=update,
            prev_reaction_id=int(reaction_id),
        )
