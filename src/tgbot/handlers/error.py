import html
import logging
import traceback

from telegram import Update
from telegram.error import Forbidden
from telegram.ext import ContextTypes

from src.tgbot.constants import UserType
from src.tgbot.logs import log
from src.tgbot.service import update_user
from src.tgbot.user_info import update_user_info_cache


async def send_stacktrace_to_tg_chat(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id
    logging.error("Exception while handling an update:", exc_info=context.error)

    # if the error is that we can't send them a message,
    #  then handle it as not a real error.
    if isinstance(context.error, Forbidden):
        await log(f"User #{user_id} blocked the bot")
        await update_user(user_id, type=UserType.BLOCKED_BOT)
        await update_user_info_cache(user_id)
        return

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
