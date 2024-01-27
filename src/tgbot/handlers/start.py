import logging
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from src import localizer
from src.tgbot.service import (
    save_tg_user,
    save_user,
    add_user_language,
)

from src.tgbot.senders.next_message import next_message
from src.tgbot.constants import (
    DEFAULT_USER_LANGUAGE, 
    UserType,
)
from src.storage.constants import SUPPORTED_LANGUAGES
from src.tgbot.handlers.onboarding import onboarding_flow


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    deep_link = context.args[0] if context.args else None 
    language_code = update.effective_user.language_code

    await save_tg_user(
        id=user_id,
        username=update.effective_user.username,
        first_name=update.effective_user.first_name,
        last_name=update.effective_user.last_name,
        is_premium=update.effective_user.is_premium,
        language_code=language_code,
        deep_link=deep_link,
    )

    if deep_link and deep_link.startswith("s_"):  # invited
        user_type = UserType.USER
    else:
        user_type = UserType.WAITLIST

    user = await save_user(
        id=user_id,
        type=user_type,
    )

    if language_code is None:
        language_code = DEFAULT_USER_LANGUAGE

    if language_code in SUPPORTED_LANGUAGES:
        await add_user_language(user_id, language_code)
    else:
        await add_user_language(user_id, DEFAULT_USER_LANGUAGE)
        logging.info(f"User(id={user_id}) has unsupported language_code={language_code}. Set default={DEFAULT_USER_LANGUAGE}.")

    if user["type"] == UserType.WAITLIST:
        await update.effective_user.send_message(
            localizer.t("onboarding_joined_waitlist", language_code),
            parse_mode=ParseMode.HTML,
        )
        return
    
    recently_joined = user["created_at"] > datetime.utcnow() - timedelta(minutes=60)
    if recently_joined:
        return await onboarding_flow(update)

    return await next_message(
        user_id,
        prev_update=update,
        prev_reaction_id=None,
    )

    
