from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from src.stats.service import get_user_stats


async def handle_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    report = await get_user_stats_report(update.effective_user.id)

    await update.message.reply_text(
        f"""
<code>🤓 Your stats 🧐</code>
{report}

/leaderboard /kitchen /uploads /chat
        """,
        parse_mode=ParseMode.HTML,
    )


async def get_user_stats_report(user_id: int) -> str:
    user_stats = await get_user_stats(user_id)

    report = ""
    if user_stats:
        for k, v in user_stats.items():
            report += f"<b>{k}</b>: {v}\n"

    return report
