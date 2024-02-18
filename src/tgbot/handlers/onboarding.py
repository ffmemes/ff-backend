import asyncio

from telegram import Update
from telegram.constants import ParseMode

from src import localizer
from src.recommendations.meme_queue import generate_cold_start_recommendations
from src.tgbot.senders.next_message import next_message
from src.tgbot.user_info import get_user_info


# not sure about the best args for that func
async def onboarding_flow(update: Update):
    user_id = update.effective_user.id
    user_info = await get_user_info(user_id)

    # TODO: select language flow

    await update.effective_user.send_message(
        localizer.t("onboarding.welcome_message", user_info["language_code"]),
        parse_mode=ParseMode.HTML,
    )

    await generate_cold_start_recommendations(user_id)
    await asyncio.sleep(8)

    m = await update.effective_user.send_message("3️⃣")
    await asyncio.sleep(1.5)
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
