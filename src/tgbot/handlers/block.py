"""
    Handles user blocking the bot
"""


from datetime import datetime

from telegram import Update

from src.stats.service import get_user_stats
from src.stats.user import calculate_user_stats
from src.tgbot.constants import UserType
from src.tgbot.logs import log
from src.tgbot.service import update_user


async def user_blocked_bot_handler(update: Update, context):
    """Handle an event when user blocks us"""
    user_tg = user_id = update.my_chat_member.from_user
    user_id = user_tg.id
    user = await update_user(
        user_id, blocked_bot_at=datetime.utcnow(), type=UserType.BLOCKED_BOT
    )

    # send user info to admin log chat
    # it's useful to analyze churned users
    await calculate_user_stats()  # regenerate user stats
    user_stats = await get_user_stats(user_id)

    report = ""
    if user_stats:
        for k, v in user_stats.items():
            report += f"<b>{k}</b>: {v}\n"

    message = f"""
⛔️ <b>BLOCKED</b> by {user_tg.name} / #{user_id}
<b>registered</b>: {user["created_at"]}
{report}
    """
    await log(message)
