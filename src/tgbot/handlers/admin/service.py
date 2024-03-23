from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from src.database import (
    execute,
    fetch_all,
    fetch_one,
    user,
    user_tg,
)
from src.tgbot.constants import UserType


async def delete_user(user_id: int) -> None:
    await execute(user.delete().where(user.c.id == user_id))
    await execute(user_tg.delete().where(user_tg.c.id == user_id))


async def get_user_by_tg_username(
    username: str,
) -> dict[str, Any] | None:
    select_statement = (
        select(user)
        .select_from(user_tg.join(user, user_tg.c.id == user.c.id))
        .where(func.lower(user_tg.c.username) == username.lower())
    )
    return await fetch_one(select_statement)


async def get_waitlist_users_registered_before(
    date: datetime,
) -> list[dict[str, Any]]:
    """Select all users that have registered before or at a certain datetime"""
    select_statement = select(user).where(
        user.c.created_at <= date, user.c.type == UserType.WAITLIST
    )
    return await fetch_all(select_statement)
