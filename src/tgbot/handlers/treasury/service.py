import asyncio
from typing import Any

from sqlalchemy import exists, func, select, text

from src.database import execute, fetch_all, fetch_one, treasury_trx, user
from src.tgbot.handlers.treasury.constants import TrxType

LEADERBOARD_WINDOW_DAYS = 7


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


def _recent_earnings_subquery():
    window_start = func.now() - text(f"INTERVAL '{LEADERBOARD_WINDOW_DAYS} days'")

    return (
        select(
            treasury_trx.c.user_id.label("user_id"),
            func.sum(treasury_trx.c.amount).label("weekly_earned"),
        )
        .where(treasury_trx.c.created_at >= window_start)
        .where(treasury_trx.c.amount > 0)
        .group_by(treasury_trx.c.user_id)
        .subquery()
    )


async def get_leaderboard(limit=10) -> list[dict[str, Any]]:
    recent_earnings = _recent_earnings_subquery()

    select_statement = (
        select(user, recent_earnings.c.weekly_earned)
        .join(recent_earnings, recent_earnings.c.user_id == user.c.id)
        .order_by(recent_earnings.c.weekly_earned.desc(), user.c.id.asc())
        .limit(limit)
    )

    return await fetch_all(select_statement)


async def get_token_supply() -> int:
    select_statement = select(func.sum(treasury_trx.c.amount))
    result = await execute(select_statement)
    return result.scalar()


async def get_user_place_in_leaderboard(user_id: int) -> int:
    recent_earnings = _recent_earnings_subquery()

    ranked_users = (
        select(
            user.c.id.label("id"),
            user.c.nickname.label("nickname"),
            user.c.balance.label("balance"),
            recent_earnings.c.weekly_earned.label("weekly_earned"),
            func.row_number()
            .over(
                order_by=(
                    recent_earnings.c.weekly_earned.desc(),
                    user.c.id.asc(),
                )
            )
            .label("place"),
        )
        .join(recent_earnings, recent_earnings.c.user_id == user.c.id)
        .subquery()
    )

    select_statement = select(ranked_users).where(ranked_users.c.id == user_id)

    return await fetch_one(select_statement)


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


async def transfer_tokens(from_user_id: int, to_user_id: int, amount: int):
    # TODO: atomic
    # Create negative transaction for sender
    await create_treasury_trx(
        user_id=from_user_id,
        type=TrxType.SEND,
        amount=-amount,
        external_id=str(to_user_id),
    )

    # Create positive transaction for recipient
    await create_treasury_trx(
        user_id=to_user_id,
        type=TrxType.RECEIVE,
        amount=amount,
        external_id=str(from_user_id),
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
        .where(treasury_trx.c.external_id == str(external_id))
        .select()
    )
    res = await execute(exists_statement)
    return res.scalar()
