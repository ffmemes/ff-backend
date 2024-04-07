import asyncio

from telegram import Update
from telegram.constants import ParseMode

from src import localizer
from src.tgbot.senders.next_message import next_message
from src.tgbot.user_info import update_user_info_cache


# not sure about the best args for that func
async def onboarding_flow(update: Update):
    user_id = update.effective_user.id
    user_info = await update_user_info_cache(user_id)

    # TODO: select language flow

    await update.effective_user.send_message(
        localizer.t("onboarding.welcome_message", user_info["interface_lang"]),
        parse_mode=ParseMode.HTML,
    )

    await asyncio.sleep(10)

    m = await update.effective_user.send_message("3️⃣")
    await asyncio.sleep(2)
    m = await m.edit_text("2️⃣")
    await asyncio.sleep(2)
    m = await m.edit_text("1️⃣")
    await asyncio.sleep(2)
    m = await m.edit_text("💣")
    await asyncio.sleep(2.5)
    await m.delete()

    return await next_message(
        user_id,
        prev_update=update,
        prev_reaction_id=None,
    )
