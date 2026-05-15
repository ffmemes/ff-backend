from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from src.tgbot.handlers.chat import service


def _telegram_message(
    *,
    message_id: int,
    user_id: int,
    text: str,
    chat: SimpleNamespace | None = None,
    reply_to_message: SimpleNamespace | None = None,
) -> SimpleNamespace:
    chat = chat or SimpleNamespace(
        id=-100123,
        type="supergroup",
        title="Moderator Chat",
        username=None,
    )

    return SimpleNamespace(
        message_id=message_id,
        date=datetime(2026, 5, 15, 9, 58, 57, tzinfo=timezone.utc),
        chat=chat,
        from_user=SimpleNamespace(id=user_id),
        sender_chat=None,
        text=text,
        caption=None,
        reply_to_message=reply_to_message,
        photo=None,
        video=None,
        animation=None,
        document=None,
        sticker=None,
        voice=None,
        video_note=None,
        media_group_id=None,
        forward_origin=None,
    )


async def test_save_telegram_message_self_heals_missing_reply_context(monkeypatch):
    rows = []

    async def fake_execute(query):
        rows.append(query.compile(dialect=postgresql.dialect()).params)

    async def noop_upsert_chat(_chat):
        return None

    monkeypatch.setattr(service, "execute", fake_execute)
    monkeypatch.setattr(service, "upsert_telegram_chat", noop_upsert_chat)

    source_vote = _telegram_message(
        message_id=100,
        user_id=999,
        text="Добавляем новый источник мемов?",
    )
    reply = _telegram_message(
        message_id=101,
        user_id=123,
        text="Вроде бы все ок",
        chat=source_vote.chat,
        reply_to_message=source_vote,
    )

    await service.save_telegram_message(reply)

    assert [row["message_id"] for row in rows] == [100, 101]
    assert rows[0]["text"] == "Добавляем новый источник мемов?"
    assert rows[0]["reply_to_message_id"] is None
    assert rows[1]["text"] == "Вроде бы все ок"
    assert rows[1]["reply_to_message_id"] == 100
