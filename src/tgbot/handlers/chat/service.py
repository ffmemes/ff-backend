import logging

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from telegram import (
    Message,
    MessageOriginChannel,
    MessageOriginChat,
    MessageOriginUser,
)

from src.database import (
    execute,
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


def _extract_media(msg: Message) -> tuple[str | None, str | None]:
    """Return (media_type, best-quality file_id) or (None, None) for text-only messages."""
    if msg.photo:
        return "photo", msg.photo[-1].file_id
    if msg.video:
        return "video", msg.video.file_id
    if msg.animation:
        return "animation", msg.animation.file_id
    if msg.document:
        return "document", msg.document.file_id
    if msg.sticker:
        return "sticker", msg.sticker.file_id
    if msg.voice:
        return "voice", msg.voice.file_id
    if msg.video_note:
        return "video_note", msg.video_note.file_id
    return None, None


def _extract_forward(msg: Message) -> tuple[int | None, int | None, int | None]:
    """Return (forward_from_chat_id, forward_from_message_id, forward_from_user_id)."""
    origin = getattr(msg, "forward_origin", None)
    if origin is None:
        return None, None, None
    if isinstance(origin, MessageOriginUser):
        return None, None, origin.sender_user.id
    if isinstance(origin, MessageOriginChat):
        return origin.sender_chat.id, None, None
    if isinstance(origin, MessageOriginChannel):
        return origin.chat.id, origin.message_id, None
    # MessageOriginHiddenUser: no usable id.
    return None, None, None


async def save_telegram_message(msg: Message) -> None:
    reply_to_message = getattr(msg, "reply_to_message", None)
    if reply_to_message is not None:
        try:
            await _save_telegram_message_row(reply_to_message)
        except Exception as e:
            logger.warning(
                "Failed to save reply target %s for message %s in chat %s: %s",
                getattr(reply_to_message, "message_id", None),
                getattr(msg, "message_id", None),
                getattr(getattr(msg, "chat", None), "id", None),
                e,
            )

    return await _save_telegram_message_row(msg)


async def _save_telegram_message_row(msg: Message) -> None:
    # Prefer sender_chat when present (anonymous channel posts)
    sender_chat_id = None
    user_id = None
    reply_to_message = getattr(msg, "reply_to_message", None)

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

    media_type, file_id = _extract_media(msg)
    fwd_chat_id, fwd_msg_id, fwd_user_id = _extract_forward(msg)

    query = (
        insert(message_tg)
        .values(
            message_id=msg.message_id,
            date=msg.date.replace(tzinfo=None),
            chat_id=msg.chat.id,
            user_id=user_id,
            sender_chat_id=sender_chat_id,
            text=msg.text or msg.caption,
            reply_to_message_id=reply_to_message.message_id if reply_to_message else None,
            media_type=media_type,
            file_id=file_id,
            media_group_id=msg.media_group_id,
            forward_from_chat_id=fwd_chat_id,
            forward_from_message_id=fwd_msg_id,
            forward_from_user_id=fwd_user_id,
        )
        .on_conflict_do_nothing()
    )
    return await execute(query)
