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
    execute, fetch_one, fetch_all,
)

from src.storage.constants import Language


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
    )

    await execute(insert_statement)


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


async def def_user_language(
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
