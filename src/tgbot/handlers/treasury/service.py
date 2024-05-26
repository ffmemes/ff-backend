import asyncio
from typing import Any

from sqlalchemy import exists, func, select, text

from src.database import execute, fetch_all, fetch_one, treasury_trx, user
from src.tgbot.handlers.treasury.constants import TrxType


async def calculate_user_balance(user_id: int):
    select_statement = select(func.sum(treasury_trx.c.amount)).where(
        treasury_trx.c.user_id == user_id
    )
    result = await execute(select_statement)
    return result.scalar()


async def update_user_balance(user_id: int, amount: int):
    # we can store balance_updated_at and fetch trx only after that date
    await execute(user.update().where(user.c.id == user_id).values(balance=amount))


async def get_user_balance(user_id: int) -> int:
    user_balance = await calculate_user_balance(user_id)
    if user_balance:
        asyncio.create_task(update_user_balance(user_id, user_balance))
    return user_balance or 0


async def get_leaderboard(limit=10) -> list[dict[str, Any]]:
    select_statement = select(user).order_by(user.c.balance.desc()).limit(limit)
    return await fetch_all(select_statement)


async def get_user_place_in_leaderboard(user_id: int) -> int:
    return await fetch_one(
        text(
            f"""
                SELECT
                    id, nickname, place, balance
                FROM (
                    SELECT
                        ROW_NUMBER() OVER (ORDER BY balance DESC) place,
                        id,
                        nickname,
                        balance
                    FROM
                        "user"
                ) with_row_number
                WHERE id = {user_id}
            """
        )
    )


async def create_treasury_trx(
    user_id: int,
    type: TrxType,
    amount: int,
    external_id: str | None = None,
):
    return await execute(
        treasury_trx.insert().values(
            user_id=user_id,
            type=type,
            amount=amount,
            external_id=external_id,
        )
    )


async def check_if_treasury_trx_exists(
    user_id: int,
    type: TrxType,
    external_id: str | None = None,
) -> bool:
    exists_statement = (
        exists(treasury_trx)
        .where(treasury_trx.c.user_id == user_id)
        .where(treasury_trx.c.type == type)
        .where(treasury_trx.c.external_id == external_id)
        .select()
    )
    res = await execute(exists_statement)
    return res.scalar()
