import logging

from telegram.error import Forbidden

from src import localizer
from src.tgbot.bot import bot
from src.tgbot.user_info import get_user_info


def _format_burgers(amount: int | None) -> str:
    return f"{int(amount or 0):,}".replace(",", " ")


async def send_successfull_invitation_alert(
    invitor_user_id: int,
    invited_user_name: str,
    balance: int,
    reward_amount: int,
) -> None:
    user_info = await get_user_info(invitor_user_id)

    try:
        await bot.send_message(
            chat_id=invitor_user_id,
            text=localizer.t(
                "onboarding.invitation_successful_alert",
                user_info["interface_lang"],
            ).format(
                invited_user_name=invited_user_name,
                balance=_format_burgers(balance),
                reward_amount=reward_amount,
            ),
        )
    except Forbidden:
        logging.info("Invitation alert skipped: user %s blocked the bot", invitor_user_id)
