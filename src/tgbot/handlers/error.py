import html
import logging
import traceback

from telegram import Update
from telegram.error import Forbidden
from telegram.ext import ContextTypes

from src.tgbot.constants import (
    TELEGRAM_CHANNEL_EN_LINK,
    TELEGRAM_CHANNEL_RU_LINK,
    UserType,
)
from src.tgbot.logs import log
from src.tgbot.service import get_user_languages, update_user
from src.tgbot.user_info import update_user_info_cache


async def send_stacktrace_to_tg_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        pass

    user_id = update.effective_user.id

    logging.error("Exception while handling an update:", exc_info=context.error)

    # if the error is that we can't send them a message,
    #  then handle it as not a real error.
    if isinstance(context.error, Forbidden):
        await log(f"User #{user_id} blocked the bot", context.bot)
        await update_user(user_id, type=UserType.BLOCKED_BOT)
        await update_user_info_cache(user_id)
        return

    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = html.escape("".join(tb_list))

    # cut first lines to fit tg msg len limit
    if len(tb_string) > 3000:
        tb_string = tb_string[-3000:]

    message = f"An exception was raised while handling an update\n<pre>{tb_string}</pre>"

    base_message = """
😔 Something broke inside the bot. It is still early beta.
We already received all the details.
Wait for 2 minutes and press /start.

👩🏻‍💻👨‍💻🧑🏻‍💻
    """

    try:
        languages = set(await get_user_languages(user_id))
        language_code = update.effective_user.language_code if update.effective_user else None
        if language_code:
            languages.add(language_code)

        has_russian = any(language and language.startswith("ru") for language in languages)
        channel_link = TELEGRAM_CHANNEL_RU_LINK if has_russian else TELEGRAM_CHANNEL_EN_LINK

        if has_russian:
            channel_message = f"🎯 Пока мы всё чиним, мемы можно ловить тут: {channel_link}"
        else:
            channel_message = f"🎯 While we are fixing things, memes live here: {channel_link}"

        await context.bot.send_message(
            text=f"{base_message}\n\n{channel_message}",
            chat_id=user_id,
        )
    except Exception:  # noqa: BLE001
        logging.exception("Failed to send crash message with channel link")
        try:
            await context.bot.send_message(
                text=base_message,
                chat_id=user_id,
            )
        except Exception:  # noqa: BLE001
            logging.exception("Failed to send crash message fallback")

    error_text_to_send = f"⚠️⚠️⚠️ for #{user_id}:\n{message}"
    return await log(error_text_to_send, context.bot)
