from src.database import (
    execute,
    user,
    user_tg,
)


async def delete_user(user_id: int) -> None:
    await execute(user.delete().where(user.c.id == user_id))
    await execute(user_tg.delete().where(user_tg.c.id == user_id))
