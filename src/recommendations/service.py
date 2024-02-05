import logging
from datetime import datetime
from typing import Any

from sqlalchemy import exists, select, text
from sqlalchemy.dialects.postgresql import insert

from src.database import (
    execute,
    fetch_all,
    user_meme_reaction,
)
from src.recommendations.utils import exclude_meme_ids_sql_filter


async def create_user_meme_reaction(
    user_id: int,
    meme_id: int,
    recommended_by: str,
) -> None:
    insert_query = (
        insert(user_meme_reaction)
        .values(
            user_id=user_id,
            meme_id=meme_id,
            recommended_by=recommended_by,
        )
        .on_conflict_do_nothing(
            index_elements=(user_meme_reaction.c.user_id, user_meme_reaction.c.meme_id)
        )
    )
    await execute(insert_query)


async def update_user_meme_reaction(
    user_id: int,
    meme_id: int,
    reaction_id: int,
) -> bool:
    update_query = (
        user_meme_reaction.update()
        .where(user_meme_reaction.c.user_id == user_id)
        .where(user_meme_reaction.c.meme_id == meme_id)
        .where(user_meme_reaction.c.reaction_id.is_(None))  # not sure abot that
        .values(reaction_id=reaction_id, reacted_at=datetime.utcnow())
    )
    res = await execute(update_query)
    reaction_is_new = res.rowcount > 0
    if not reaction_is_new:
        logging.warning(f"User {user_id} already reacted to meme {meme_id}!")
    return reaction_is_new  # I can filter double clicks


# test handler, will be removed
async def get_unseen_memes(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
) -> list[dict[str, Any]]:
    query = f"""
        SELECT
            M.id, M.type, M.telegram_file_id, M.caption,
            'test' as recommended_by
        FROM meme M
        LEFT JOIN user_meme_reaction R
            ON R.meme_id = M.id
            AND R.user_id = {user_id}
        INNER JOIN user_language L
            ON L.user_id = {user_id}
            AND L.language_code = M.language_code
        WHERE 1=1
            AND M.status = 'ok'
            AND R.meme_id IS NULL
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}
        LIMIT {limit}
    """
    res = await fetch_all(text(query))
    return res


async def get_user_reactions(
    user_id: int,
) -> list[dict[str, Any]]:
    select_statement = select(user_meme_reaction).where(
        user_meme_reaction.c.user_id == user_id
    )
    return await fetch_all(select_statement)


async def user_meme_reaction_exists(
    user_id: int,
    meme_id: int,
) -> bool:
    exists_statement = (
        exists(user_meme_reaction)
        .where(user_meme_reaction.c.user_id == user_id)
        .where(user_meme_reaction.c.meme_id == meme_id)
        .select()
    )
    res = await execute(exists_statement)
    return res.scalar()
