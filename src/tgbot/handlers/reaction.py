"""Handle reactions on sent memes."""

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from src.flows.rewards.daily import reward_user_for_daily_activity
from src.recommendations.service import (
    update_user_last_active_at,
    update_user_meme_reaction,
)
from src.tgbot.handlers.moderator.invite import maybe_send_moderator_invite
from src.tgbot.senders.next_message import next_message
from src.tgbot.user_info import update_user_info_counters


def _fire_and_forget(coro):
    """Schedule a coroutine as a fire-and-forget task, swallowing exceptions."""
    task = asyncio.create_task(coro)
    task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
    return task


async def handle_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    meme_id, reaction_id = update.callback_query.data[2:].split(":")
    logging.info(f"🛜 reaction: user_id={user_id}, meme_id={meme_id}, reaction_id={reaction_id}")

    # do that in sync since we'll use counters in next_message
    user_info = await update_user_info_counters(user_id)
    await maybe_send_moderator_invite(context.bot, user_id, user_info)
    _fire_and_forget(update_user_last_active_at(user_id))
    _fire_and_forget(reward_user_for_daily_activity(user_id))

    reaction_is_new = await update_user_meme_reaction(
        user_id=user_id,
        meme_id=int(meme_id),
        reaction_id=int(reaction_id),
    )

    if reaction_is_new:
        return await next_message(
            context.bot,
            user_id,
            prev_update=update,
            prev_reaction_id=int(reaction_id),
        )
