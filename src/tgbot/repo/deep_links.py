from sqlalchemy.dialects.postgresql import insert

from src.database import execute, user_deep_link_log


async def log_user_deep_link(user_id: int, deep_link: str | None) -> None:
    insert_query = insert(user_deep_link_log).values(
        user_id=user_id,
        deep_link=deep_link,
    )
    await execute(insert_query)
