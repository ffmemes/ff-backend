import logging

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from telegram import Message

from src.database import (
    execute,
    fetch_all,
    message_tg,
)

logger = logging.getLogger(__name__)


async def save_telegram_message(msg: Message) -> None:
    if not msg.from_user:
        return
    query = (
        insert(message_tg)
        .values(
            message_id=msg.message_id,
            date=msg.date.replace(tzinfo=None),
            chat_id=msg.chat.id,
            user_id=msg.from_user.id,
            text=msg.text or msg.caption,
            reply_to_message_id=msg.reply_to_message.message_id if msg.reply_to_message else None,
        )
        .on_conflict_do_nothing()
    )
    return await execute(query)


async def get_active_chat_users(chat_id: int, limit: int = 10):
    select_query = text("""
        WITH ACTIVE_USERS AS (
            SELECT MSG.user_id, MAX(MSG.date) date
            FROM message_tg MSG
            INNER JOIN "user" U
                ON U.id = MSG.user_id
            WHERE U.blocked_bot_at IS NULL
            AND MSG.chat_id = :chat_id
            GROUP BY 1
            ORDER BY 2 DESC
            LIMIT :limit
        )

        SELECT
            ACTIVE_USERS.user_id,
            UT.username, UT.first_name
        FROM ACTIVE_USERS
        INNER JOIN user_tg UT
            ON UT.id = ACTIVE_USERS.user_id
    """)
    return await fetch_all(select_query, {"chat_id": chat_id, "limit": limit})


async def get_latest_chat_messages(chat_id: int, limit: int = 20):
    select_query = text("""
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
            U1.name AS from_name,
            COALESCE(U2.name, NULL) AS reply_to_name,
            M.text
        FROM message_tg M
            LEFT JOIN message_tg M2
                ON M.reply_to_message_id = M2.message_id
                AND M2.chat_id = :chat_id
            INNER JOIN USER_NAMES U1
                ON M.user_id = U1.id
            LEFT JOIN USER_NAMES U2
                ON M2.user_id = U2.id
        WHERE M.chat_id = :chat_id
        ORDER BY M.date DESC
        LIMIT :limit
    """)
    return await fetch_all(select_query, {"chat_id": chat_id, "limit": limit})
