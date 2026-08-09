import logging
from datetime import datetime

from sqlalchemy import exists
from sqlalchemy.dialects.postgresql import insert

from src.database import execute, user_popup_logs


async def user_popup_already_sent(
    user_id: int,
    popup_id: str,
) -> bool:
    exists_statement = (
        exists(user_popup_logs)
        .where(user_popup_logs.c.user_id == user_id)
        .where(user_popup_logs.c.popup_id == popup_id)
        .select()
    )
    res = await execute(exists_statement)
    return res.scalar()


async def create_user_popup_log(
    user_id: int,
    popup_id: str,
) -> bool:
    # Returns True if a new row was inserted (caller "won the lease"), False if a
    # row already existed. Callers that need atomic single-fire semantics can use
    # the return value as a lease — see maybe_send_first_meme_nudge.
    insert_query = (
        insert(user_popup_logs)
        .values(
            user_id=user_id,
            popup_id=popup_id,
        )
        .on_conflict_do_nothing(
            index_elements=(user_popup_logs.c.user_id, user_popup_logs.c.popup_id)
        )
    )
    result = await execute(insert_query)
    return result.rowcount > 0


async def delete_user_popup_log(
    user_id: int,
    popup_id: str,
) -> None:
    await execute(
        user_popup_logs.delete()
        .where(user_popup_logs.c.user_id == user_id)
        .where(user_popup_logs.c.popup_id == popup_id)
    )


async def update_user_popup_log(
    user_id: int,
    popup_id: int,
) -> bool:
    update_query = (
        user_popup_logs.update()
        .where(user_popup_logs.c.user_id == user_id)
        .where(user_popup_logs.c.popup_id == popup_id)
        .where(user_popup_logs.c.reacted_at.is_(None))  # not sure abot that
        .values(reacted_at=datetime.utcnow())
    )
    res = await execute(update_query)
    reaction_is_new = res.rowcount > 0
    if not reaction_is_new:
        logging.warning(f"User {user_id} already reacted to popup {popup_id}!")
    return reaction_is_new  # so I can filter double clicks
