from sqlalchemy import func

from src.database import engine, user
from src.tgbot.repo.users import create_or_update_user


async def test_create_or_update_user_reports_created_and_unblocks():
    try:
        row, created = await create_or_update_user(id=90501)
        assert created is True and row["id"] == 90501 and row["type"] == "user"

        async with engine.begin() as conn:
            await conn.execute(
                user.update()
                .where(user.c.id == 90501)
                .values(type="blocked_bot", blocked_bot_at=func.now())
            )
        row, created = await create_or_update_user(id=90501)
        assert created is False and row["type"] == "user" and row["blocked_bot_at"] is None
    finally:
        async with engine.begin() as conn:
            await conn.execute(user.delete().where(user.c.id == 90501))
