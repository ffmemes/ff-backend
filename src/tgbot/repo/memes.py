from typing import Any

from sqlalchemy import select, text

from src.database import fetch_all, fetch_one, meme, meme_stats
from src.storage.constants import MemeStatus


async def get_meme_by_id(
    id: int,
) -> dict[str, Any] | None:
    select_statement = select(meme).where(meme.c.id == id)
    return await fetch_one(select_statement)


async def get_shareable_meme_by_id(id: int) -> dict[str, Any] | None:
    query = """
        SELECT
            M.id,
            M.type,
            M.telegram_file_id,
            M.caption,
            M.language_code,
            'share_link' AS recommended_by,
            COALESCE(MS.nlikes, 0) AS nlikes
        FROM meme M
        LEFT JOIN meme_stats MS
            ON MS.meme_id = M.id
        WHERE M.id = :id
            AND M.status = :status
            AND M.telegram_file_id IS NOT NULL
    """
    return await fetch_one(text(query), {"id": id, "status": MemeStatus.OK.value})


async def get_last_reacted_meme_for_user(user_id: int) -> dict[str, Any] | None:
    """Most recently *reacted* meme (like or skip) that can still be re-sent.

    /last exists so users can fix an accidental reaction. The latest *sent*
    meme is often still on screen (no reaction yet) — that is not useful.
    """
    query = """
        SELECT
            M.id,
            M.type,
            M.telegram_file_id,
            M.caption,
            M.language_code,
            'last' AS recommended_by,
            COALESCE(MS.nlikes, 0) AS nlikes
        FROM user_meme_reaction R
        JOIN meme M
            ON M.id = R.meme_id
        LEFT JOIN meme_stats MS
            ON MS.meme_id = M.id
        WHERE R.user_id = :user_id
            AND R.reaction_id IS NOT NULL
            AND M.status = :status
            AND M.telegram_file_id IS NOT NULL
        ORDER BY R.reacted_at DESC NULLS LAST, R.sent_at DESC
        LIMIT 1
    """
    return await fetch_one(
        text(query),
        {"user_id": user_id, "status": MemeStatus.OK.value},
    )


# Back-compat alias for older imports/tests.
get_last_sent_meme_for_user = get_last_reacted_meme_for_user


async def get_meme_stats(meme_id: int) -> dict[str, Any] | None:
    select_statement = select(meme_stats).where(meme_stats.c.meme_id == meme_id)
    return await fetch_one(select_statement)


async def get_meme_stats_for_meme_ids(meme_ids: list[int]) -> list[dict[str, Any]]:
    select_statement = select(meme_stats).where(meme_stats.c.meme_id.in_(meme_ids))
    return await fetch_all(select_statement)
