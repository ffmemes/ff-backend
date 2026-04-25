"""
    Handles user blocking the bot
"""


from datetime import datetime, timezone

from telegram import Update

from src.tgbot.constants import UserType
from src.tgbot.service import update_user


async def user_blocked_bot_handler(update: Update, context):
    """Handle an event when user blocks us"""
    user_id = update.my_chat_member.from_user.id
    await update_user(
        user_id,
        blocked_bot_at=datetime.now(timezone.utc).replace(tzinfo=None),
        type=UserType.BLOCKED_BOT,
    )
