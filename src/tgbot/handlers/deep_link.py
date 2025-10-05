import re
from datetime import datetime

from telegram import Bot

from src.tgbot.constants import UserType
from src.tgbot.handlers.treasury.constants import TrxType
from src.tgbot.handlers.treasury.payments import pay_if_not_paid_with_alert
from src.tgbot.logs import log
from src.tgbot.senders.invite import send_successfull_invitation_alert
from src.tgbot.service import (
    get_tg_user_by_id,
    get_user_by_id,
    update_user,
)

LINK_UNDER_MEME_PATTERN = r"s_\d+_\d+"


async def handle_invited_user(
    bot: Bot,
    invited_user: dict,
    invited_user_name: str,
    deep_link: str | None,
):
    if not deep_link or not re.match(LINK_UNDER_MEME_PATTERN, deep_link):
        return

    _, user_id, _ = deep_link.split("_")
    invitor_user_id = int(user_id)

    # get invitor user
    invitor_user = await get_user_by_id(invitor_user_id)
    if not invitor_user:
        return  # Invitor doesn't exist

    if invitor_user_id == invited_user["id"]:
        return  # can't invite yourself

    # should not fire, adding just for debugging
    if invited_user.get("inviter_id"):
        return await log(
            f"""
User #{invited_user["id"]}/{invited_user_name}
was already invited by #{invited_user["inviter_id"]}"""
        )

    # set inviter id
    await update_user(invited_user["id"], inviter_id=invitor_user_id)

    # dont reward if a user blocked the bot
    if invitor_user["type"] == UserType.BLOCKED_BOT:
        return await log(
            f"""
❌ {invited_user_name} was invited by #{invitor_user_id}
but his type is {invitor_user["type"]}
        """
        )

    invited_user_tg = await get_tg_user_by_id(invited_user["id"])
    trx_type = (
        TrxType.USER_INVITER_PREMIUM
        if invited_user_tg and invited_user_tg.get("is_premium")
        else TrxType.USER_INVITER
    )

    paid = await pay_if_not_paid_with_alert(
        bot,
        invitor_user_id,
        trx_type,
        external_id=str(invited_user["id"]),
    )

    if paid:
        await send_successfull_invitation_alert(invitor_user_id, invited_user_name)
        await log(f"🤝 #{invitor_user_id} invited {invited_user_name}")


async def handle_shared_meme_reward(
    bot: Bot,
    clicked_user_id: int,
    deep_link: str | None,
):
    if not deep_link or not re.match(LINK_UNDER_MEME_PATTERN, deep_link):
        return

    _, user_id, _ = deep_link.split("_")
    invitor_user_id = int(user_id)

    if clicked_user_id == invitor_user_id:
        return  # don't reward clicking on your links

    today = datetime.today().date().strftime("%Y-%m-%d")
    await pay_if_not_paid_with_alert(
        bot,
        invitor_user_id,
        type=TrxType.MEME_SHARED,
        external_id=today,
    )
