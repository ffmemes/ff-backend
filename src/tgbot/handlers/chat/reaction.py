import asyncio
import logging
import random

from telegram import Update
from telegram.constants import ReactionEmoji
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from src.tgbot.constants import MESSAGE_REACTIONS

logger = logging.getLogger(__name__)
SUPPORTED_MESSAGE_REACTIONS = tuple(
    reaction for reaction in MESSAGE_REACTIONS if reaction in set(ReactionEmoji)
)


async def give_random_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Explain a tg channel post to the user
    Handle message from channel in a chat
    """
    if not update.message:
        return

    if random.random() > 0.1:
        return  # set reaction only to lucky replies

    if not SUPPORTED_MESSAGE_REACTIONS:
        return

    await asyncio.sleep(random.random() * 5)

    reaction = random.choice(SUPPORTED_MESSAGE_REACTIONS)
    try:
        await update.message.set_reaction(reaction=reaction, is_big=True)
    except BadRequest as e:
        logger.warning("Skipping unsupported chat reaction %r: %s", reaction, e)
    except Forbidden:
        logger.info("Skipping chat reaction because bot lacks permission")
