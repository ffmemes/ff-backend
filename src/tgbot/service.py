import logging
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import exists, func, select, text
from sqlalchemy.dialects.postgresql import insert

from src.database import (
    execute,
    fetch_all,
    fetch_one,
    meme,
    meme_source,
    user,
    user_language,
    user_popup_logs,
    user_tg,
)
from src.tgbot.constants import UserType


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


async def create_user(
    id: int,
) -> None:
    """
    Creates a row in user table
    If a user is already exist, it updates user's status (real sql below)
    """
    sql = f"""
        INSERT
        INTO "user"
        (id, type, last_active_at)
        VALUES ({id}, 'waitlist', NOW())
        ON CONFLICT(id)
        DO UPDATE SET
            blocked_bot_at = NULL,
            last_active_at = NOW(),
            type = CASE
                WHEN "user".type = 'blocked_bot' THEN 'waitlist'
                ELSE "user".type
            END
        RETURNING "user".*
    """

    return await fetch_one(text(sql))


async def get_user_by_id(
    id: int,
) -> dict[str, Any] | None:
    select_statement = select(user).where(user.c.id == id)
    return await fetch_one(select_statement)


async def get_waitlist_users_registered_before(
    date: datetime,
) -> list[dict[str, Any]]:
    """Select all users that have registered before or at a certain datetime"""
    select_statement = select(user).where(
        user.c.created_at <= date, user.c.type == UserType.WAITLIST
    )
    return await fetch_all(select_statement)


async def get_tg_user_by_id(
    id: int,
) -> dict[str, Any] | None:
    select_statement = select(user_tg).where(user_tg.c.id == id)
    return await fetch_one(select_statement)


async def get_user_by_tg_username(
    username: str,
) -> dict[str, Any] | None:
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


async def get_user_languages(
    user_id: int,
) -> set[str]:
    select_statement = select(user_language).where(user_language.c.user_id == user_id)
    rows = await fetch_all(select_statement)
    return set(row["language_code"] for row in rows)


async def add_user_language(
    user_id: int,
    language_code: str,
) -> None:
    insert_language_query = (
        insert(user_language)
        .values({"user_id": user_id, "language_code": language_code})
        .on_conflict_do_nothing(
            index_elements=(user_language.c.user_id, user_language.c.language_code)
        )
    )

    await execute(insert_language_query)


async def add_user_languages(
    user_id: int,
    language_codes: Sequence[str],
) -> None:
    # Prepare a list of dictionaries where each dictionary represents
    # the values to be inserted for one row.
    values_to_insert = [
        {"user_id": user_id, "language_code": language_code}
        for language_code in language_codes
    ]

    insert_language_query = (
        insert(user_language)
        .values(values_to_insert)
        .on_conflict_do_nothing(
            index_elements=(user_language.c.user_id, user_language.c.language_code)
        )
    )

    await execute(insert_language_query)


async def del_user_language(
    user_id: int,
    language_code: str,
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
    # TODO: not sure about logic behind interface_lang
    query = f"""
        WITH MEMES_WATCHED_TODAY AS (
            SELECT user_id, COUNT(*) memes_watched_today
            FROM user_meme_reaction
            WHERE 1=1
                AND reacted_at >= DATE(NOW())
                AND user_id = {user_id}
            GROUP BY 1
        ),
        USER_INTERFACE_LANG AS (
            SELECT DISTINCT ON (user_id)
                user_id,
                language_code AS interface_lang,
                CASE
                    WHEN language_code = 'en' THEN 0
                    WHEN language_code = 'ru' THEN 1
                    ELSE 2
                END score
            FROM user_language UL
            WHERE user_id = {user_id}
            ORDER BY 1, 3 DESC
        )

        SELECT
            type,
            COALESCE(nmemes_sent, 0) nmemes_sent,
            COALESCE(memes_watched_today, 0) memes_watched_today,
            UIL.interface_lang
        FROM "user" AS U
        LEFT JOIN user_stats US
            ON US.user_id = U.id
        LEFT JOIN USER_INTERFACE_LANG UIL
            ON UIL.user_id = U.id
        LEFT JOIN MEMES_WATCHED_TODAY
            ON MEMES_WATCHED_TODAY.user_id = U.id
        WHERE U.id = {user_id}
    """

    return await fetch_one(text(query))


async def update_user(user_id: int, **kwargs) -> dict[str, Any] | None:
    update_query = (
        user.update().where(user.c.id == user_id).values(**kwargs).returning(user)
    )
    return await fetch_one(update_query)


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
    await execute(insert_query)


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
