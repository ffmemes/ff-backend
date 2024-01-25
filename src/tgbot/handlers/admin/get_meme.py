"""
    Handle /add_mod <new_moderator_user_id_or_username> admin command
"""

from telegram import Update
from telegram.ext import (
    ContextTypes,
)
from src.storage.schemas import BasicMemeData
from src.tgbot.constants import UserType
from src.tgbot.senders.meme import send_new_message_with_meme

from src.tgbot.service import get_meme_by_id, get_user_by_id


async def handle_get_meme(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends you the meme by it's id"""
    user = await get_user_by_id(update.effective_user.id)
    if user["type"] not in [UserType.ADMIN, UserType.MODERATOR]:
        return

    message_split = update.message.text.split()
    if len(message_split) < 2:
        await update.message.reply_text("Please specify a meme_id")
        return
    if not message_split[1].isdigit():
        await update.message.reply_text("Please specify a valid meme_id (a number!)")
        return

    meme_id = int(message_split[1])
    meme = BasicMemeData(**await get_meme_by_id(meme_id))
    await send_new_message_with_meme(update.effective_user.id, meme)
