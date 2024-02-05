from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from src.tgbot.constants import UserType
from src.tgbot.handlers.deep_link import handle_deep_link_used
from src.tgbot.handlers.language import init_user_languages_from_tg_user
from src.tgbot.handlers.onboarding import onboarding_flow
from src.tgbot.senders.next_message import next_message
from src.tgbot.service import (
    save_tg_user,
    save_user,
)


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

    user = await save_user(id=user_id, type=UserType.WAITLIST)
    await init_user_languages_from_tg_user(update.effective_user)

    await handle_deep_link_used(
        invited_user=user,
        invited_user_name=update.effective_user.name,
        deep_link=deep_link,
    )

    # if user["type"] == UserType.WAITLIST:
    #     await update.effective_user.send_message(
    #         localizer.t("onboarding_joined_waitlist", language_code),
    #         parse_mode=ParseMode.HTML,
    #     )
    #     return

    recently_joined = user["created_at"] > datetime.utcnow() - timedelta(minutes=60)
    if recently_joined:
        return await onboarding_flow(update)

    return await next_message(
        user_id,
        prev_update=update,
        prev_reaction_id=None,
    )
