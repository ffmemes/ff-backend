"""
    Handles user blocking the bot
"""


from telegram import Update

from src.tgbot.service import update_user_blocked_bot


async def user_blocked_bot_handler(update: Update, context):
    """Handle an event when user blocks us"""
    user_id = update.my_chat_member.from_user.id
    await update_user_blocked_bot(user_id)

