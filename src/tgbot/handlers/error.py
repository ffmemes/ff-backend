import html
import logging
import traceback

from telegram import Update
from telegram.ext import ContextTypes

from src.tgbot.logs import log


async def send_stacktrace_to_tg_chat(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id
    logging.error("Exception while handling an update:", exc_info=context.error)

    tb_list = traceback.format_exception(
        None, context.error, context.error.__traceback__
    )
    tb_string = html.escape("".join(tb_list))

    # cut first lines to fit tg msg len limit
    if len(tb_string) > 4000:
        tb_string = tb_string[-4000:]

    message = (
        f"An exception was raised while handling an update\n" f"<pre>{tb_string}</pre>"
    )

    await context.bot.send_message(
        text="""
😔 Something broke inside the bot. It is still early beta.
We already received all the details.
Wait for 2 minutes and press /start.

👩🏻‍💻👨‍💻🧑🏻‍💻
        """,
        chat_id=user_id,
    )

    error_text_to_send = f"⚠️⚠️⚠️ for #{user_id}:\n{message}"
    return await log(error_text_to_send)
