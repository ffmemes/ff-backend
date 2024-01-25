from typing import Any
from datetime import datetime
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from src.database import (
    meme_source,
    user,
    user_tg,
    user_language,
    meme,
    execute,
    fetch_one,
)

from src.storage.constants import Language
from sqlalchemy import func


async def save_tg_user(
    id: int,
    **kwargs,
) -> None:
    insert_statement = (
        insert(user_tg)
        .values({"id": id, **kwargs})
        .on_conflict_do_update(
            index_elements=(user_tg.c.id,),
            set_={"updated_at": datetime.utcnow()},
            # do we need to update more fields if a user already exists?
        )
    )

    await execute(insert_statement)
    # do not return the same data


async def save_user(
    id: int,
    **kwargs,
) -> None:
    insert_statement = (
        insert(user)
        .values({"id": id, **kwargs})
        .on_conflict_do_update(
            index_elements=(user.c.id,),
            set_={
                "last_active_at": datetime.utcnow(),
                "blocked_bot_at": None,
            },
        )
        .returning(user)
    )

    return await fetch_one(insert_statement)


async def update_user(
    id: int,
    **kwargs,
) -> None:
    update_statement = (
        user.update().where(user.c.id == id).values(kwargs).returning(user)
    )

    return await fetch_one(update_statement)


async def get_user_by_id(
    id: int,
) -> dict[str, Any] | None:
    select_statement = select(user).where(user.c.id == id)
    return await fetch_one(select_statement)


async def get_tg_user_by_id(
    id: int,
) -> dict[str, Any] | None:
    select_statement = select(user_tg).where(user_tg.c.id == id)
    return await fetch_one(select_statement)


async def get_user_by_username(
    username: str,
) -> dict[str, Any] | None:
    """Slower version of `get_user_by_id`, since it requires a join. Shouldn't be used often"""
    # select user.id from user_tg join user on user_tg.id = user.id where user_tg.username = 'username';
    select_statement = (
        select(user)
        .select_from(user_tg.join(user, user_tg.c.id == user.c.id))
        .where(func.lower(user_tg.c.username) == username.lower())
    )
    return await fetch_one(select_statement)


async def get_meme_source_by_id(
    id: int,
) -> dict[str, Any] | None:
    select_statement = select(meme_source).where(meme_source.c.id == id)
    return await fetch_one(select_statement)


async def get_meme_by_id(
    id: int,
) -> dict[str, Any] | None:
    select_statement = select(meme).where(meme.c.id == id)
    return await fetch_one(select_statement)


async def get_or_create_meme_source(
    url: str,
    **kwargs,
) -> dict[str, Any] | None:
    insert_statement = (
        insert(meme_source)
        .values({"url": url, **kwargs})
        .on_conflict_do_update(
            index_elements=(meme_source.c.url,),
            set_={"updated_at": datetime.utcnow()},
        )
        .returning(meme_source)
    )

    return await fetch_one(insert_statement)


async def update_meme_source(
    id: int,
    **kwargs,
) -> dict[str, Any] | None:
    update_statement = (
        meme_source.update()
        .where(meme_source.c.id == id)
        .values({"updated_at": datetime.utcnow(), **kwargs})
        .returning(meme_source)
    )

    return await fetch_one(update_statement)


async def add_user_language(
    user_id: int,
    language_code: Language,
) -> None:
    insert_language_query = (
        insert(user_language)
        .values({"user_id": user_id, "language_code": language_code})
        .on_conflict_do_nothing(
            index_elements=(user_language.c.user_id, user_language.c.language_code)
        )
    )

    await execute(insert_language_query)


async def del_user_language(
    user_id: int,
    language_code: Language,
) -> None:
    delete_language_query = (
        user_language.delete()
        .where(user_language.c.user_id == user_id)
        .where(user_language.c.language_code == language_code)
    )

    await execute(delete_language_query)


async def get_user_info(
    user_id: int,
) -> dict[str, Any] | None:
    # TODO: calculate memes_watched_today inside user_stats
    query = f"""
        WITH MEMES_WATCHED_TODAY AS (
            SELECT user_id, COUNT(*) memes_watched_today
            FROM user_meme_reaction
            WHERE user_id = {user_id}
            AND reacted_at >= DATE(NOW())
            GROUP BY 1
        )

        SELECT 
            type, 
            COALESCE(nmemes_sent, 0) nmemes_sent, 
	        COALESCE(memes_watched_today, 0) memes_watched_today
        FROM "user" AS U
        LEFT JOIN user_stats US 
            ON US.user_id = U.id
        LEFT JOIN MEMES_WATCHED_TODAY
            ON MEMES_WATCHED_TODAY.user_id = U.id
        WHERE U.id = {user_id};
    """

    return await fetch_one(text(query))


# async def sync_user_language(
#     user_id: int,
#     language_code: list[str],
# ) -> None:
#     languages
#     posts = [
#         post.model_dump(exclude_none=True) | {"meme_source_id": meme_source_id}
#         for post in telegram_posts
#     ]
#     insert_statement = insert(meme_raw_telegram).values(posts)
#     insert_posts_query = insert_statement.on_conflict_do_update(
#         constraint=MEME_SOURCE_POST_UNIQUE_CONSTRAINT,
#         set_={
#             "media": insert_statement.excluded.media,
#             "views": insert_statement.excluded.views,
#             "updated_at": datetime.utcnow(),
#         },
#     )

#     await execute(insert_posts_query)
