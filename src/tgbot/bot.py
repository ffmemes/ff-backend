# Used in cases when we need to send a message to a user

from telegram import Bot

from src.config import settings

bot = Bot(settings.TELEGRAM_BOT_TOKEN)
