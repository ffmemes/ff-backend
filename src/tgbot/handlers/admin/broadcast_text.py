from telegram import Update
from telegram.ext import (
    ContextTypes,
)

from src.broadcasts.service import get_users_with_language
from src.tgbot.constants import UserType
from src.tgbot.user_info import get_user_info


async def handle_broadcast_text_ru(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Receives a forward from tgchannelru
    And forwards it to all users who
    1. don't follow the channel
    2. hadn't seen this meme yet
    3. set language ru
    """
    user = await get_user_info(update.effective_user.id)
    if user["type"] != UserType.ADMIN:
        return

    text = update.message.text.replace("/broadcastru", "").strip()
    if not text:
        return

    await update.message.reply_text(
        f"Going to broadcast this text to ru users:\n\n{text}",
        parse_mode="HTML",
    )


async def handle_broadcast_text_ru_trigger(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = await get_user_info(update.effective_user.id)
    if user["type"] != UserType.ADMIN:
        return

    text = update.message.text.replace("/broadcastru1", "").strip()
    if not text:
        return

    users = await get_users_with_language("ru")
    user_ids = [user["id"] for user in users]

    await update.message.reply_text(
        f"Going to broadcast this text to {len(user_ids)} ru users:\n\n{text}",
        parse_mode="HTML",
    )

    for user_id in user_ids:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode="HTML",
            )
        except Exception as e:
            print(f"Failed to send message to {user_id}: {e}")
            # TODO: proper hanlder & logging
