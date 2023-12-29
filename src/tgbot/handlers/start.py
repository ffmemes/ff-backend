import logging
from telegram import Update
from telegram.ext import (
    ContextTypes, 
)


from src.tgbot.service import (
    save_tg_user,
    save_user,
    add_user_language,
)

from src.storage.constants import SUPPORTED_LANGUAGES
from src.tgbot.constants import DEFAULT_USER_LANGUAGE, UserType


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

    await save_user(
        id=user_id,
        type=UserType.USER,
        blocked_bot_at=None,
    )

    if language_code is None:
        language_code = DEFAULT_USER_LANGUAGE

    if language_code in SUPPORTED_LANGUAGES:
        await add_user_language(user_id, language_code)
    else:
        await add_user_language(user_id, DEFAULT_USER_LANGUAGE)
        logging.info(f"User(id={user_id}) has unsupported language_code={language_code}. Set default={DEFAULT_USER_LANGUAGE}.")

    
    await update.effective_user.send_message("Hi! You just joined our waitlist. Stay tuned!")
        
