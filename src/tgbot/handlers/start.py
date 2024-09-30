import asyncio
import re

from telegram import Update
from telegram.ext import ContextTypes

from src.tgbot.handlers.deep_link import LINK_UNDER_MEME_PATTERN, handle_deep_link_used
from src.tgbot.handlers.language import (
    handle_language_settings,
    init_user_languages_from_tg_user,
)
from src.tgbot.logs import log
from src.tgbot.service import (
    create_user,
    get_tg_user_by_id,
    log_user_deep_link,
    save_tg_user,
)
from src.tgbot.user_info import update_user_info_cache


async def save_user_data(user_id: int, update: Update, deep_link: str | None):
    tg_user = await get_tg_user_by_id(user_id)
    language_code = update.effective_user.language_code

    await save_tg_user(
        id=user_id,
        username=update.effective_user.username,
        first_name=update.effective_user.first_name,
        last_name=update.effective_user.last_name,
        is_premium=update.effective_user.is_premium,
        language_code=language_code,
        deep_link=deep_link
        if tg_user is None
        or tg_user["deep_link"] is None
        or not re.match(LINK_UNDER_MEME_PATTERN, tg_user["deep_link"])
        else None,
    )

    await log_user_deep_link(user_id, deep_link)
    return await create_user(id=user_id)


async def handle_deep_link_if_present(context, user, user_name, deep_link):
    if deep_link:
        return asyncio.create_task(
            handle_deep_link_used(
                bot=context.bot,
                invited_user=user,
                invited_user_name=user_name,
                deep_link=deep_link,
            )
        )


async def log_start_event(update, user_info, deep_link, language_code, context):
    if deep_link:
        return asyncio.create_task(
            log(
                f"""
👋 {update.effective_user.name}/#{update.effective_user.id}
type:{user_info["type"]}, ref:{deep_link}, lang:{language_code}
        """,
                context.bot,
            )
        )


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    deep_link = context.args[0] if context.args else None
    language_code = update.effective_user.language_code

    user = await save_user_data(user_id, update, deep_link)
    await init_user_languages_from_tg_user(update.effective_user)

    await handle_deep_link_if_present(
        context, user, update.effective_user.name, deep_link
    )

    user_info = await update_user_info_cache(user_id)
    await log_start_event(update, user_info, deep_link, language_code, context)

    return await handle_language_settings(update, context)
