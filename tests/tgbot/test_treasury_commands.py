from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.tgbot.handlers.treasury import commands
from src.tgbot.handlers.treasury.constants import PAYOUTS, TrxType


def _make_update(user_id: int = 10001):
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        message=SimpleNamespace(reply_text=AsyncMock(), reply_video=AsyncMock()),
    )


def _make_context():
    return SimpleNamespace()


@pytest.mark.asyncio
async def test_kitchen_uses_russian_when_ru_enabled(monkeypatch) -> None:
    update = _make_update()
    monkeypatch.setattr(commands, "get_user_languages", AsyncMock(return_value={"ru", "en"}))

    await commands.handle_show_kitchen(update, _make_context())

    caption = update.message.reply_video.call_args.kwargs["caption"]
    assert "<b>🍔 Кухня</b>" in caption
    assert "Как получить бургеры" in caption
    assert (
        f"если принятый мем попадет в наш канал: {PAYOUTS[TrxType.MEME_PUBLISHED]} 🍔"
        in caption
    )
    assert (
        "кто-то нажал ссылку под мемом, которым ты поделился: "
        f"{PAYOUTS[TrxType.MEME_SHARED]} 🍔 раз в день"
        in caption
    )


@pytest.mark.asyncio
async def test_kitchen_uses_english_when_ru_not_enabled(monkeypatch) -> None:
    update = _make_update()
    monkeypatch.setattr(commands, "get_user_languages", AsyncMock(return_value={"uk"}))

    await commands.handle_show_kitchen(update, _make_context())

    caption = update.message.reply_video.call_args.kwargs["caption"]
    assert "<b>🍔 Kitchen</b>" in caption
    assert "How to get more burgers" in caption
    assert (
        f"if an approved meme reaches our channel: {PAYOUTS[TrxType.MEME_PUBLISHED]} 🍔"
        in caption
    )
    assert "Как получить бургеры" not in caption


@pytest.mark.asyncio
async def test_leaderboard_uses_russian_when_ru_enabled(monkeypatch) -> None:
    update = _make_update()
    monkeypatch.setattr(commands, "get_user_languages", AsyncMock(return_value={"ru"}))
    monkeypatch.setattr(commands, "get_random_emoji", lambda: "⭐")
    monkeypatch.setattr(
        commands,
        "get_leaderboard",
        AsyncMock(return_value=[{"nickname": "Alice & Bob", "weekly_earned": 1234}]),
    )
    monkeypatch.setattr(commands, "get_token_supply", AsyncMock(return_value=533831))
    monkeypatch.setattr(
        commands,
        "get_user_place_in_leaderboard",
        AsyncMock(return_value={"place": 2, "nickname": "Me", "weekly_earned": 50}),
    )

    await commands.handle_show_leaderbaord(update, _make_context())

    text = update.message.reply_text.call_args.args[0]
    assert "Лидерборд за последние" in text
    assert "Alice &amp; Bob - 1 234 🍔" in text
    assert "Всего в обороте: 533 831 🍔" in text
    assert "Ты:" in text


@pytest.mark.asyncio
async def test_leaderboard_uses_english_when_ru_not_enabled(monkeypatch) -> None:
    update = _make_update()
    monkeypatch.setattr(commands, "get_user_languages", AsyncMock(return_value={"uk"}))
    monkeypatch.setattr(commands, "get_random_emoji", lambda: "⭐")
    monkeypatch.setattr(
        commands,
        "get_leaderboard",
        AsyncMock(return_value=[{"nickname": "Alice", "weekly_earned": 1234}]),
    )
    monkeypatch.setattr(commands, "get_token_supply", AsyncMock(return_value=533831))
    monkeypatch.setattr(
        commands,
        "get_user_place_in_leaderboard",
        AsyncMock(return_value={"place": 2, "nickname": "Me", "weekly_earned": 50}),
    )

    await commands.handle_show_leaderbaord(update, _make_context())

    text = update.message.reply_text.call_args.args[0]
    assert "Leaderboard (last" in text
    assert "Total supply: 533 831 🍔" in text
    assert "You:" in text
    assert "Лидерборд" not in text
