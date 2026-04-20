"""
Handle reactions on sent memes
"""

import asyncio
import logging

from telegram import Update
from telegram.ext import (
    ContextTypes,
)

from src.flows.events import safe_emit
from src.recommendations.service import update_user_last_active_at
from src.tgbot.senders.next_message import next_message
from src.tgbot.service import update_user_popup_log

logger = logging.getLogger(__name__)

CHANNEL_POPUP_ID = "popup.telegram_channel"
SUBSCRIPTION_CHECK_DELAY_SECONDS = 30


async def _check_channel_subscription(bot, user_id: int) -> None:
    await asyncio.sleep(SUBSCRIPTION_CHECK_DELAY_SECONDS)
    try:
        from src.tgbot.user_info import get_user_info
        from src.tgbot.utils import check_if_user_follows_related_channel

        user_info = await get_user_info(user_id)
        if user_info is None:
            return

        is_member = await check_if_user_follows_related_channel(
            bot, user_id, user_info["interface_lang"]
        )
        if is_member:
            safe_emit(
                "ff.popup.telegram_channel.subscribed",
                f"user.{user_id}",
                {"user_id": user_id},
            )
    except Exception:
        logger.exception("Failed to check channel subscription for user %s", user_id)


async def handle_popup_button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    user_id = update.effective_user.id
    popup_id = update.callback_query.data[2:]
    reaction_is_new = await update_user_popup_log(user_id, popup_id)

    asyncio.create_task(update_user_last_active_at(user_id))

    if popup_id == CHANNEL_POPUP_ID and reaction_is_new:
        safe_emit(
            "ff.popup.telegram_channel.clicked",
            f"user.{user_id}",
            {"user_id": user_id},
        )
        asyncio.create_task(_check_channel_subscription(context.bot, user_id))

    if reaction_is_new:
        return await next_message(
            context.bot,
            user_id,
            prev_update=update,
            prev_reaction_id=None,
        )
