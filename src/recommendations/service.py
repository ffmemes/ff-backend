from typing import Any
from datetime import datetime
from sqlalchemy import select, nulls_first, text
from sqlalchemy.dialects.postgresql import insert

from src.database import (
    language,
    meme,
    meme_source,
    user,
    user_tg,
    user_language,
    meme_raw_telegram,
    user_meme_reaction,
    execute, fetch_one, fetch_all,
)


async def create_user_meme_reaction(
    user_id: int,
    meme_id: int,
    recommended_by: str,
    telegram_message_id: int,
) -> None:
    insert_query = insert(user_meme_reaction).values(
        user_id=user_id,
        meme_id=meme_id,
        recommended_by=recommended_by,
        telegram_message_id=telegram_message_id,
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
    res = await fetch_one(update_query)
    reaction_is_new = res is not None  # because I added filter reaction_id IS NULL
    return reaction_is_new  # I can filter double clicks

