import asyncio
from datetime import datetime

from telegram import Update
from telegram.ext import (
    ContextTypes,
)

from src import localizer
from src.tgbot.bot import bot
from src.tgbot.constants import UserType
from src.tgbot.logs import log
from src.tgbot.service import (
    get_waitlist_users_registered_before,
    update_user,
)
from src.tgbot.user_info import get_user_info, update_user_info_cache


async def handle_allow_waitlist_invite(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Gives access to everyone, who is registered before a certain date"""
    user = await get_user_info(update.effective_user.id)
    if user["type"] != UserType.ADMIN:
        return

    message_split = update.message.text.split(" ")
    if len(message_split) != 2:
        await update.message.reply_text(
            "USAGE: /allow yyyy-mm-dd\n"
            "Allows everyone registered before and during that day to the bot."
        )
        return

    date_str = message_split[1]
    try:
        date = datetime.strptime(date_str, "%Y-%m-%d")
        # set h, m, s to 23:59:59
        date = date.replace(hour=23, minute=59, second=59)
    except ValueError:
        await update.message.reply_text("Invalid date format. Use /allow yyyy-mm-dd")
        return

    # get all users registered that day
    users = await get_waitlist_users_registered_before(date)
    await update.message.reply_text(
        f"Inviting {len(users)} users registered before and on date {date_str}."
    )
    await log(
        f"Inviting {len(users)} users registered before and on date {date_str}.",
    )
    # separate the for loop in batches of 20
    for i, user in enumerate(users):
        await invite_user(user["id"])
        await asyncio.sleep(0.1)
        if i % 25 == 0 and i != 0:
            await update.message.reply_text(
                f"✅ Invited {i + 1}/{len(users)} users registered before {date_str}."
                "\nSleeping for 1.5s",
            )

    await update.message.reply_text(
        f"✅ Invited {len(users)} users registered before {date_str}."
    )


async def invite_user(user_id: int) -> None:
    await update_user(user_id, type=UserType.USER)
    user_info = await update_user_info_cache(user_id)
    await bot.send_message(
        user_id,
        localizer.t("onboarding.invited_by_admin", user_info["interface_lang"]),
    )
