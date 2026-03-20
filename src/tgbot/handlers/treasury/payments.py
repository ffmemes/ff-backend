"""
Additional layer of control for treasury payments
"""

import asyncio
import logging

from telegram import Bot
from telegram.error import Forbidden

from src.tgbot.handlers.treasury.constants import (
    PAYOUTS,
    TRX_TYPE_DESCRIPTIONS,
    TREASURY_USER_ID,
    TrxType,
)
from src.tgbot.handlers.treasury.service import (
    check_if_treasury_trx_exists,
    create_treasury_trx,
    get_user_balance,
)
from src.tgbot.logs import log


async def pay_if_not_paid(
    user_id: int,
    type: TrxType,
    external_id: str,
) -> int | None:
    if await check_if_treasury_trx_exists(user_id, type, external_id=external_id):
        return

    _ = await create_treasury_trx(
        user_id,
        type,
        PAYOUTS[type],
        external_id=external_id,
    )

    return await get_user_balance(user_id)


async def charge_user(
    user_id: int,
    type: TrxType,
    external_id: str,
) -> int | None:
    if PAYOUTS[type] >= 0:
        return  # this is only for payments

    await create_treasury_trx(
        user_id=user_id,
        type=type,
        amount=PAYOUTS[type],
        external_id=external_id,
    )

    # Create positive transaction for recipient
    await create_treasury_trx(
        user_id=TREASURY_USER_ID,
        type=type,
        amount=PAYOUTS[type] * (-1),
        external_id=external_id,
    )

    return await get_user_balance(user_id)


async def mint_tokens(
    user_id: int,
    amount: int,
    external_id: str,
):
    if await check_if_treasury_trx_exists(user_id, TrxType.PURCHASE_TOKEN, external_id=external_id):
        return

    _ = await create_treasury_trx(
        user_id,
        TrxType.PURCHASE_TOKEN,
        amount,
        external_id=external_id,
    )

    return await get_user_balance(user_id)


async def pay_if_not_paid_with_alert(
    bot: Bot,
    user_id: int,
    type: TrxType,
    external_id: str,
) -> int | None:
    # TODO: atomic?
    res = await pay_if_not_paid(user_id, type, external_id)
    if res:
        try:
            msg = await bot.send_message(
                chat_id=user_id,
                text=f"""
    💳 /b: +<b>{PAYOUTS[type]} 🍔</b> for <b>{TRX_TYPE_DESCRIPTIONS[type]}</b>!
                """,
                parse_mode="HTML",
            )
        except Forbidden:
            logging.info("Payment alert skipped: user %s blocked the bot", user_id)
            return res

        if msg.chat.username:
            user_name = "@" + msg.chat.username
        else:
            user_name = msg.chat.effective_name

        # ruff: noqa
        asyncio.create_task(
            log(f"💳 {user_name}/{user_id}: +{PAYOUTS[type]} 🍔 for {TRX_TYPE_DESCRIPTIONS[type]}")
        )

    return res
