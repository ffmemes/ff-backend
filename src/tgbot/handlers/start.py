from telegram import Update
from telegram.ext import ContextTypes

from src.tgbot.handlers.deep_link import handle_deep_link_used
from src.tgbot.handlers.language import (
    handle_language_settings,
    init_user_languages_from_tg_user,
)
from src.tgbot.logs import log
from src.tgbot.service import create_user, save_tg_user
from src.tgbot.user_info import update_user_info_cache


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

    user = await create_user(id=user_id)
    await init_user_languages_from_tg_user(update.effective_user)
    if deep_link:
        await handle_deep_link_used(
            invited_user=user,
            invited_user_name=update.effective_user.name,
            deep_link=deep_link,
        )

    user_info = await update_user_info_cache(user_id)

    await log(
        f"""
👋 {update.effective_user.name}/#{user_id}
type:{user_info["type"]}, ref:{deep_link}, lang:{language_code}
    """
    )

    return await handle_language_settings(update, context)
