import asyncio
from datetime import datetime

from telegram import Update
from telegram.ext import (
    ContextTypes,
)

from src import localizer
from src.tgbot.bot import bot
from src.tgbot.constants import UserType
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
            "USAGE: /allow dd-mm-yyyy\n"
            "Allows everyone registered before and during that day to the bot."
        )
        return

    date_str = message_split[1]
    try:
        date = datetime.strptime(date_str, "%d-%m-%Y")
        # set h, m, s to 23:59:59
        date = date.replace(hour=23, minute=59, second=59)
    except ValueError:
        await update.message.reply_text("Invalid date format. Use /allow dd-mm-yyyy")
        return

    total_count = 0
    # get all users registered that day
    users = await get_waitlist_users_registered_before(date)
    await update.message.reply_text(
        f"Inviting {len(users)} users registered before and on date {date_str}."
    )
    # separate the for loop in batches of 20
    for user_batch in [users[i : i + 20] for i in range(0, len(users), 20)]:
        tasks = []
        for user in user_batch:
            tasks.append(invite_user(user["id"], user["interface_lang"]))
        await asyncio.gather(*tasks)
        total_count += len(tasks)

        await update.message.reply_text(
            f"✅ Invited {total_count}/{len(users)} users registered before {date_str}."
            "\nSleeping for 1.5s",
        )
        await asyncio.sleep(1.5)


async def invite_user(user_id: int, user_language: str) -> None:
    await update_user(user_id, type=UserType.USER)
    await update_user_info_cache(user_id)
    await bot.send_message(
        user_id,
        localizer.t("onboarding.invited_by_admin", user_language),
    )
