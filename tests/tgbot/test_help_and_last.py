from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.storage.constants import MemeType
from src.tgbot.commands_catalog import PUBLIC_COMMANDS, menu_bot_commands
from src.tgbot.handlers import help as help_handlers
from src.tgbot.handlers import private_message_log


def _make_update(user_id: int = 10001):
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )


def _make_context():
    return SimpleNamespace(bot=object())


def test_menu_bot_commands_last_is_first():
    for lang in (None, "ru", "en", "uk"):
        cmds = menu_bot_commands(lang)
        assert [c.command for c in cmds][0] == "last"
        assert [c.command for c in cmds] == ["last", "help"]
    assert menu_bot_commands("ru")[0].description == "Предыдущий мем"
    assert "start" not in {c.command for c in menu_bot_commands()}
    assert PUBLIC_COMMANDS >= {"last", "help", "previous", "prev"}


@pytest.mark.asyncio
async def test_help_uses_russian_when_interface_lang_ru(monkeypatch):
    update = _make_update()
    monkeypatch.setattr(
        help_handlers,
        "get_user_info",
        AsyncMock(return_value={"interface_lang": "ru"}),
    )

    await help_handlers.handle_help(update, _make_context())

    text = update.message.reply_text.call_args.args[0]
    assert "/last" in text
    assert "Лента" in text or "лайк" in text
    assert "Как получить бургеры" not in text


@pytest.mark.asyncio
async def test_help_uses_english_fallback(monkeypatch):
    update = _make_update()
    monkeypatch.setattr(
        help_handlers,
        "get_user_info",
        AsyncMock(return_value={"interface_lang": "de"}),
    )

    await help_handlers.handle_help(update, _make_context())

    text = update.message.reply_text.call_args.args[0]
    assert "Feed:" in text
    assert "/last" in text


@pytest.mark.asyncio
async def test_last_replies_when_no_history(monkeypatch):
    update = _make_update()
    monkeypatch.setattr(
        help_handlers,
        "get_user_info",
        AsyncMock(return_value={"interface_lang": "ru"}),
    )
    monkeypatch.setattr(
        help_handlers,
        "get_last_sent_meme_for_user",
        AsyncMock(return_value=None),
    )

    await help_handlers.handle_last(update, _make_context())

    text = update.message.reply_text.call_args.args[0]
    assert "/start" in text


@pytest.mark.asyncio
async def test_last_resends_meme(monkeypatch):
    update = _make_update(user_id=42)
    send = AsyncMock()
    monkeypatch.setattr(
        help_handlers,
        "get_user_info",
        AsyncMock(return_value={"interface_lang": "en"}),
    )
    monkeypatch.setattr(
        help_handlers,
        "get_last_sent_meme_for_user",
        AsyncMock(
            return_value={
                "id": 99,
                "type": MemeType.IMAGE,
                "telegram_file_id": "file-1",
                "caption": "hi",
                "language_code": "ru",
                "recommended_by": "last",
                "nlikes": 3,
            }
        ),
    )
    monkeypatch.setattr(help_handlers, "send_meme_to_user", send)

    await help_handlers.handle_last(update, _make_context())

    send.assert_awaited_once()
    kwargs = send.call_args.kwargs
    assert kwargs["recommended_by"] == "last"
    meme = send.call_args.args[2]
    assert meme.id == 99
    update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_private_inbound_log_uses_message_tg(monkeypatch):
    saved = AsyncMock()
    monkeypatch.setattr(private_message_log, "save_telegram_message", saved)

    msg = SimpleNamespace(message_id=7, text="/last")
    update = SimpleNamespace(
        message=msg,
        effective_user=SimpleNamespace(id=42),
    )
    await private_message_log.log_private_inbound_message(update, SimpleNamespace())

    saved.assert_awaited_once_with(msg)


@pytest.mark.asyncio
async def test_private_inbound_log_swallows_errors(monkeypatch):
    monkeypatch.setattr(
        private_message_log,
        "save_telegram_message",
        AsyncMock(side_effect=RuntimeError("db down")),
    )
    update = SimpleNamespace(
        message=SimpleNamespace(message_id=1, text="/help"),
        effective_user=SimpleNamespace(id=1),
    )
    # Must not raise
    await private_message_log.log_private_inbound_message(update, SimpleNamespace())
