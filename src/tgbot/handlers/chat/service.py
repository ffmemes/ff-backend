import logging

from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert
from telegram import Message

from src.database import (
    execute,
    fetch_all,
    message_tg,
    telegram_chat,
)

logger = logging.getLogger(__name__)


async def upsert_telegram_chat(chat) -> None:
    """Persist chat/channel metadata. Works with Chat, SenderChat, etc."""
    query = (
        insert(telegram_chat)
        .values(
            id=chat.id,
            type=getattr(chat, "type", None),
            title=getattr(chat, "title", None),
            username=getattr(chat, "username", None),
        )
        .on_conflict_do_update(
            index_elements=["id"],
            set_={
                "type": getattr(chat, "type", None),
                "title": getattr(chat, "title", None),
                "username": getattr(chat, "username", None),
                "updated_at": func.now(),
            },
        )
    )
    await execute(query)


async def upsert_telegram_chat_bot_joined(chat) -> None:
    """Record that the bot was added to a chat."""
    query = (
        insert(telegram_chat)
        .values(
            id=chat.id,
            type=getattr(chat, "type", None),
            title=getattr(chat, "title", None),
            username=getattr(chat, "username", None),
            bot_status="member",
            bot_joined_at=func.now(),
            updated_at=func.now(),
        )
        .on_conflict_do_update(
            index_elements=["id"],
            set_={
                "type": getattr(chat, "type", None),
                "title": getattr(chat, "title", None),
                "username": getattr(chat, "username", None),
                "bot_status": "member",
                "bot_joined_at": func.now(),
                "updated_at": func.now(),
            },
        )
    )
    await execute(query)


async def update_telegram_chat_bot_left(chat_id: int) -> None:
    """Record that the bot was removed from a chat."""
    from sqlalchemy import update

    query = (
        update(telegram_chat)
        .where(telegram_chat.c.id == chat_id)
        .values(
            bot_status="left",
            bot_left_at=func.now(),
            updated_at=func.now(),
        )
    )
    await execute(query)


async def save_telegram_message(msg: Message) -> None:
    # Prefer sender_chat when present (anonymous channel posts)
    sender_chat_id = None
    user_id = None

    if getattr(msg, "sender_chat", None):
        sender_chat_id = msg.sender_chat.id
        user_id = msg.sender_chat.id
        try:
            await upsert_telegram_chat(msg.sender_chat)
        except Exception as e:
            logger.warning("Failed to upsert sender_chat: %s", e)
    elif msg.from_user:
        user_id = msg.from_user.id
    else:
        return

    # Also persist the chat metadata
    try:
        await upsert_telegram_chat(msg.chat)
    except Exception as e:
        logger.warning("Failed to upsert chat: %s", e)

    query = (
        insert(message_tg)
        .values(
            message_id=msg.message_id,
            date=msg.date.replace(tzinfo=None),
            chat_id=msg.chat.id,
            user_id=user_id,
            sender_chat_id=sender_chat_id,
            text=msg.text or msg.caption,
            reply_to_message_id=msg.reply_to_message.message_id if msg.reply_to_message else None,
        )
        .on_conflict_do_nothing()
    )
    return await execute(query)


async def get_active_chat_users(chat_id: int, limit: int = 10):
    select_query = text(
        """
        WITH ACTIVE_USERS AS (
            SELECT MSG.user_id, MAX(MSG.date) date
            FROM message_tg MSG
            LEFT JOIN "user" U
                ON U.id = MSG.user_id
            WHERE (U.blocked_bot_at IS NULL OR U.id IS NULL)
            AND MSG.chat_id = :chat_id
            AND MSG.user_id > 0
            GROUP BY 1
            ORDER BY 2 DESC
            LIMIT :limit
        )

        SELECT
            ACTIVE_USERS.user_id,
            UT.username, UT.first_name
        FROM ACTIVE_USERS
        LEFT JOIN user_tg UT
            ON UT.id = ACTIVE_USERS.user_id
    """
    )
    return await fetch_all(select_query, {"chat_id": chat_id, "limit": limit})


async def get_latest_chat_messages(chat_id: int, limit: int = 20):
    select_query = text(
        """
        WITH USER_NAMES AS (
            SELECT
                id,
                CASE
                    WHEN username IS NOT NULL THEN '@' || username
                    WHEN first_name IS NOT NULL AND LENGTH(first_name) > 1
                        THEN first_name
                    ELSE CAST(id AS TEXT)
                END AS name
            FROM user_tg
        )

        SELECT
            M.date,
            CASE
                WHEN M.sender_chat_id IS NOT NULL THEN
                    COALESCE(TC.title, TC.username, 'channel ' || M.sender_chat_id::text)
                WHEN M.user_id < 0 THEN
                    COALESCE(TC2.title, TC2.username, 'channel ' || M.user_id::text)
                ELSE COALESCE(U1.name, CAST(M.user_id AS TEXT))
            END AS from_name,
            COALESCE(U2.name, NULL) AS reply_to_name,
            M.text
        FROM message_tg M
            LEFT JOIN message_tg M2
                ON M.reply_to_message_id = M2.message_id
                AND M2.chat_id = :chat_id
            LEFT JOIN USER_NAMES U1
                ON M.user_id = U1.id
            LEFT JOIN USER_NAMES U2
                ON M2.user_id = U2.id
            LEFT JOIN telegram_chat TC
                ON M.sender_chat_id = TC.id
            LEFT JOIN telegram_chat TC2
                ON M.user_id = TC2.id AND M.user_id < 0
        WHERE M.chat_id = :chat_id
        ORDER BY M.date DESC
        LIMIT :limit
    """
    )
    return await fetch_all(select_query, {"chat_id": chat_id, "limit": limit})
