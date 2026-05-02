import asyncio
import re

from telegram import Bot, Update
from telegram.ext import ContextTypes

from src.tgbot.handlers.deep_link import (
    LINK_UNDER_MEME_PATTERN,
    handle_invited_user,
    handle_shared_meme_reward,
)
from src.tgbot.handlers.language import (
    handle_language_settings,
    init_user_languages_from_tg_user,
)
from src.tgbot.handlers.treasury.commands import (
    handle_show_kitchen,
)
from src.tgbot.logs import log
from src.tgbot.senders.next_message import next_message
from src.tgbot.service import (
    create_or_update_user,
    get_tg_user_by_id,
    get_user_languages,
    log_user_deep_link,
    save_tg_user,
)
from src.tgbot.user_info import update_user_info_cache


async def save_user_data(user_id: int, update: Update, deep_link: str | None) -> tuple[dict, bool]:
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

    user, created = await create_or_update_user(id=user_id)
    return user, created


async def log_start_event(
    update,
    user_info,
    deep_link,
    language_code,
    bot: Bot,
    is_new: bool,
):
    return asyncio.create_task(
        log(
            f"""
👋 {update.effective_user.name}/#{update.effective_user.id}
type:{user_info["type"]}, ref:{deep_link}, lang:{language_code}, new: {is_new}
    """,
            bot,
        )
    )


# Acquisition channels with 0% super user conversion rate (cohort analysis 2026-03-29)
# Block new user onboarding from these channels to avoid wasting server resources.
# Existing users who re-open the bot via these links are served normally.
BLOCKED_ACQUISITION_CHANNELS = frozenset({"likefollowbot"})


def _is_blocked_acquisition_channel(deep_link: str | None) -> bool:
    if not deep_link:
        return False
    return deep_link in BLOCKED_ACQUISITION_CHANNELS or deep_link.startswith("tapps")


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    deep_link = context.args[0] if context.args else None
    language_code = update.effective_user.language_code

    if _is_blocked_acquisition_channel(deep_link):
        existing = await get_tg_user_by_id(user_id)
        if existing is None:
            return  # Don't onboard new users from zero-retention acquisition channels

    user, created = await save_user_data(user_id, update, deep_link)
    user_info = await update_user_info_cache(user_id)
    await log_user_deep_link(user_id, deep_link)
    await log_start_event(
        update,
        user_info,
        deep_link,
        language_code,
        context.bot,
        created,
    )

    # Ensure language rows exist before any branch that may serve memes.
    # Covers: new users on every deep_link path (kitchen used to skip init),
    # and historical orphans whose init was never run — they were stuck on
    # "memes ended" because recommendations filter by user_language.
    # Idempotent: add_user_languages uses ON CONFLICT DO NOTHING.
    if not await get_user_languages(user_id):
        await init_user_languages_from_tg_user(update.effective_user)

    if deep_link == "kitchen":
        return await handle_show_kitchen(update, context)

    if deep_link == "wrapped":
        from src.tgbot.handlers.stats.wrapped import handle_wrapped

        return await handle_wrapped(update, context)

    if created:  # new user:
        await handle_language_settings(update, context)

        await handle_invited_user(
            context.bot,
            user,
            update.effective_user.name,
            deep_link,
        )

        # handle giveaway after onboarding so user_language rows exist
        if deep_link and deep_link.startswith("giveaway_"):
            from src.tgbot.handlers.treasury.giveaway import handle_giveaway

            await handle_giveaway(update, context, deep_link)
        return
    else:  # existing user:
        if deep_link and deep_link.startswith("giveaway_"):
            from src.tgbot.handlers.treasury.giveaway import handle_giveaway

            return await handle_giveaway(update, context, deep_link)

        await next_message(
            context.bot,
            user_id,
            prev_update=update,
            prev_reaction_id=None,
        )

        await handle_shared_meme_reward(context.bot, user_id, deep_link)
        return
