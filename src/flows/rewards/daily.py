from datetime import datetime

from prefect import flow
from telegram.constants import ParseMode

from src import localizer
from src.tgbot.bot import bot
from src.tgbot.handlers.treasury.constants import PAYOUTS, TrxType
from src.tgbot.handlers.treasury.payments import pay_if_not_paid
from src.tgbot.logs import log
from src.tgbot.user_info import get_user_info


@flow
async def reward_user_for_daily_activity(user_id: int):
    user_info = await get_user_info(user_id)
    if user_info["memes_watched_today"] == 10:
        balance = await pay_if_not_paid(
            user_id,
            TrxType.DAILY_REWARD,
            datetime.today().strftime("%Y-%m-%d"),
        )
        if balance:
            interface_lang = user_info["interface_lang"]
            nmemes_sent = user_info["nmemes_sent"]

            msg = localizer.t("rewards.daily_reward", interface_lang).format(
                amount=PAYOUTS[TrxType.DAILY_REWARD]
            )
            await bot.send_message(
                user_id,
                msg,
                parse_mode=ParseMode.HTML,
            )
            await log(
                f"+daily to #{user_id}: {interface_lang}, {balance} 🍔, {nmemes_sent} 📮"  # noqa E501
            )
