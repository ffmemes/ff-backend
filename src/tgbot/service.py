from typing import Any
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from src.database import (
    meme_source,
    user,
    user_tg,
    user_language,
    execute,
    fetch_one,
)

from src.storage.constants import Language


async def save_tg_user(
    id: int,
    **kwargs,
) -> None:
    update_dict_if_user_already_created = {
        "username": kwargs["username"],
        "first_name": kwargs["first_name"],
        "last_name": kwargs["last_name"],
        "is_premium": kwargs["is_premium"],
        "language_code": kwargs["language_code"],
        "updated_at": datetime.utcnow(),
    }
    insert_statement = (
        insert(user_tg)
        .values({"id": id, **kwargs})
        .on_conflict_do_update(
            index_elements=(user_tg.c.id,),
            set_=update_dict_if_user_already_created,
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


async def get_user_by_id(
    id: int,
) -> dict[str, Any] | None:
    select_statement = select(user).where(user.c.id == id)
    return await fetch_one(select_statement)


async def get_meme_source_by_id(
    id: int,
) -> dict[str, Any] | None:
    select_statement = select(meme_source).where(meme_source.c.id == id)
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
