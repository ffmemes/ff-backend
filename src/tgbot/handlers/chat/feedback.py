import random

from telegram import Update
from telegram.ext import ContextTypes

from src.tgbot.constants import TELEGRAM_FEEDBACK_CHAT_ID


async def handle_feedback_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, message_id = update.effective_user.id, update.effective_message.message_id
    message_text = update.message.text.split(" ", 1)[-1]

    if message_text.startswith("/"):
        # user send only a command
        # TODO: localize
        await update.message.reply_text(
            """
USAGE: /chat YOUR MESSAGE HERE
HINT: you can use shorter command: /c
NOTE: we will not see messages without this command
            """
        )
        return

    header = f"{user_id}:{message_id}"

    await context.bot.send_message(
        chat_id=TELEGRAM_FEEDBACK_CHAT_ID,
        text=f"{header}\n{message_text}",
    )

    # react to the user's message to show that message was read & delivered
    reaction = random.choice(
        ["🕊", "🍾", "👾", "🔥", "🤝", "⚡", "💯", "👍", "🫡", "👌", "💅"]
    )
    await update.message.set_reaction(reaction)


async def handle_feedback_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_text = update.message.text
    header, _ = update.message.reply_to_message.text.split("\n", 1)
    user_id, message_id = header.split(":")

    await context.bot.send_message(
        chat_id=user_id,
        text=reply_text,
        reply_to_message_id=int(message_id),
    )
