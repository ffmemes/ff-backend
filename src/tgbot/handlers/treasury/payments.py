"""
    Additional layer of control for treasury payments
"""

from telegram import Bot

from src.tgbot.handlers.treasury.constants import (
    PAYOUTS,
    TRX_TYPE_DESCRIPTIONS,
    TrxType,
)
from src.tgbot.handlers.treasury.service import (
    check_if_treasury_trx_exists,
    create_treasury_trx,
    update_user_balance,
)


async def pay_if_not_paid(
    user_id: int,
    type: TrxType,
    enternal_id: str | None = None,
) -> None:
    if await check_if_treasury_trx_exists(user_id, type, external_id=enternal_id):
        return

    trx = await create_treasury_trx(
        user_id,
        type,
        PAYOUTS[type],
        external_id=enternal_id,
    )

    await update_user_balance(user_id, PAYOUTS[type])

    return trx


async def pay_if_not_paid_with_alert(
    bot: Bot,
    user_id: int,
    type: TrxType,
    enternal_id: str | None = None,
) -> None:
    if not pay_if_not_paid(user_id, type, enternal_id):
        return

    await bot.send_message(
        chat_id=user_id,
        text=f"""
💳 /b: +<b>{PAYOUTS[type]} 🍔</b> for <b>{TRX_TYPE_DESCRIPTIONS[type]}</b>!
        """,
        parse_mode="HTML",
    )
