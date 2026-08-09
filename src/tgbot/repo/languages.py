from typing import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from src.database import execute, fetch_all, user_language


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
        {"user_id": user_id, "language_code": language_code} for language_code in language_codes
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
