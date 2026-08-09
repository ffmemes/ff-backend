import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from src.database import execute, fetch_one, user, user_tg, user_tg_chat_membership
from src.tgbot.constants import UserType


async def save_tg_user(
    id: int,
    **kwargs,
) -> None:
    filtered_kwargs = {k: v for k, v in kwargs.items() if v is not None}

    insert_statement = (
        insert(user_tg)
        .values({"id": id, **filtered_kwargs})
        .on_conflict_do_update(
            index_elements=(user_tg.c.id,),
            set_={"updated_at": datetime.utcnow(), **filtered_kwargs},
        )
    )

    await execute(insert_statement)


async def create_or_update_user(
    id: int,
) -> tuple[dict, bool]:
    """
    Creates or updates a row in user table.
    Returns tuple of (user dict, bool) where bool
    indicates if user was created (True) or updated (False).
    """
    sql = f"""
        WITH upsert AS (
            INSERT
            INTO "user"
            (id, type, last_active_at)
            VALUES ({id}, '{UserType.USER.value}', NOW())
            ON CONFLICT(id)
            DO UPDATE SET
                blocked_bot_at = NULL,
                last_active_at = NOW(),
                type = CASE
                    WHEN "user".type = '{UserType.BLOCKED_BOT.value}'
                        THEN '{UserType.USER.value}'
                    ELSE "user".type
                END
            RETURNING "user".*, (xmax = 0) as created
        )
        SELECT *, created FROM upsert
    """

    result = await fetch_one(text(sql))
    created = result.pop("created")
    return result, created


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


async def add_user_tg_chat_membership(
    user_tg_id: int,
    chat_id: int,
) -> None:
    insert_query = (
        insert(user_tg_chat_membership)
        .values({"user_tg_id": user_tg_id, "chat_id": chat_id})
        .on_conflict_do_update(
            index_elements=(
                user_tg_chat_membership.c.user_tg_id,
                user_tg_chat_membership.c.chat_id,
            ),
            set_={"last_seen_at": datetime.utcnow()},
        )
    )

    await execute(insert_query)


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
            COALESCE(nsessions, 0) nsessions,
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
    update_query = user.update().where(user.c.id == user_id).values(**kwargs).returning(user)
    return await fetch_one(update_query)


def _blocked_bot_at_timestamp(when: datetime | None = None) -> datetime:
    # blocked_bot_at is TIMESTAMP WITHOUT TIME ZONE; asyncpg rejects tz-aware
    # values for this column, so persist all block events as naive UTC.
    if when is None:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if when.tzinfo is not None:
        return when.astimezone(timezone.utc).replace(tzinfo=None)
    return when


async def mark_user_blocked(
    user_id: int,
    source: str,
    when: datetime | None = None,
) -> dict[str, Any] | None:
    """Mark a user as having blocked the bot.

    Idempotent. Preserves the user's role in `type` and records the Telegram
    transport state in blocked_bot_at. The legacy `blocked_bot` user type can
    still exist on old rows, but new block events must not overwrite roles.
    Invalidates user_info cache on success.

    `source` is a free-form label for observability
    ("my_chat_member", "forbidden_send_meme", ...).
    `when` should be the Telegram event date when available
    (update.my_chat_member.date); otherwise defaults to utcnow().
    """
    from src.tgbot.user_info import update_user_info_cache  # avoid cycle

    current = await get_user_by_id(user_id)
    if current is None:
        return None

    ts = _blocked_bot_at_timestamp(when)
    try:
        current_type = UserType(current["type"]) if current["type"] else None
    except ValueError:
        current_type = None

    if current_type and current_type.is_moderator:
        logging.warning(
            "User #%s blocked via %s but is privileged (type=%s); "
            "recording blocked_bot_at, NOT demoting type",
            user_id,
            source,
            current_type.value,
        )

    updated = await update_user(user_id, blocked_bot_at=ts)

    if updated is not None:
        try:
            await update_user_info_cache(user_id)
        except Exception as exc:
            logging.warning(
                "Cache refresh failed for user #%s after block: %s",
                user_id,
                exc,
            )
        logging.info("User #%s blocked (source=%s)", user_id, source)

    return updated


async def mark_user_unblocked(
    user_id: int,
    source: str,
    when: datetime | None = None,
) -> dict[str, Any] | None:
    """Mark a user as having unblocked the bot.

    Always clears blocked_bot_at. Restores type to 'user' only if the
    user was currently 'blocked_bot' — privileged roles left alone.
    Invalidates user_info cache on success.
    """
    from src.tgbot.user_info import update_user_info_cache  # avoid cycle

    current = await get_user_by_id(user_id)
    if current is None:
        return None

    update_kwargs: dict[str, Any] = {"blocked_bot_at": None}
    if current["type"] == UserType.BLOCKED_BOT.value:
        update_kwargs["type"] = UserType.USER.value

    updated = await update_user(user_id, **update_kwargs)

    if updated is not None:
        try:
            await update_user_info_cache(user_id)
        except Exception as exc:
            logging.warning(
                "Cache refresh failed for user #%s after unblock: %s",
                user_id,
                exc,
            )
        logging.info("User #%s unblocked (source=%s)", user_id, source)

    return updated
