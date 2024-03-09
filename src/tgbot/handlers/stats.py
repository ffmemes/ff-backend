from telegram import Update
from telegram.ext import ContextTypes


async def handle_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Coming soon! 🍆")
