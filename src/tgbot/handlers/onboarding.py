from telegram import Bot, Update
from telegram.constants import ParseMode

from src import localizer
from src.tgbot.senders.next_message import next_message
from src.tgbot.user_info import update_user_info_cache


async def onboarding_flow(update: Update, bot: Bot):
    """Welcome (if still new) then the first feed meme. No 3-2-1 wait."""
    user_id = update.effective_user.id

    user_info = await update_user_info_cache(user_id)

    recently_joined = user_info["nmemes_sent"] <= 3
    if recently_joined:
        await update.effective_user.send_message(
            localizer.t("onboarding.welcome_message", user_info["interface_lang"]),
            parse_mode=ParseMode.HTML,
        )

    return await next_message(
        bot,
        user_id,
        prev_update=update,
        prev_reaction_id=None,
    )
