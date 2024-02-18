from typing import Any

from sqlalchemy import select

from src.database import fetch_one, user_stats


async def get_user_stats(
    user_id: int,
) -> dict[str, Any] | None:
    select_statement = select(user_stats).where(user_stats.c.user_id == user_id)
    return await fetch_one(select_statement)
