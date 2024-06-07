"""
    Additional layer of control for treasury payments
"""

import asyncio

from telegram import Bot

from src.tgbot.handlers.treasury.constants import (
    PAYOUTS,
    TRX_TYPE_DESCRIPTIONS,
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
    external_id: str | None = None,
) -> None:
    if await check_if_treasury_trx_exists(user_id, type, external_id=external_id):
        return

    _ = await create_treasury_trx(
        user_id,
        type,
        PAYOUTS[type],
        external_id=external_id,
    )

    return await get_user_balance(user_id)


async def pay_if_not_paid_with_alert(
    bot: Bot,
    user_id: int,
    type: TrxType,
    external_id: str | None = None,
) -> None:
    # TODO: atomic?
    if not await pay_if_not_paid(user_id, type, external_id):
        return

    await bot.send_message(
        chat_id=user_id,
        text=f"""
💳 /b: +<b>{PAYOUTS[type]} 🍔</b> for <b>{TRX_TYPE_DESCRIPTIONS[type]}</b>!
        """,
        parse_mode="HTML",
    )

    asyncio.create_task(
        log(f"💳 {user_id}: +{PAYOUTS[type]} 🍔 for {TRX_TYPE_DESCRIPTIONS[type]}")
    )
