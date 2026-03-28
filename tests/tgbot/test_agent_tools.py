"""Regression tests for chat agent tool dispatch."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_execute_send_meme_coerces_string_meme_id():
    """Regression: meme_id arriving as str from LLM JSON must be cast to int before SQL.

    Sentry FF-BACKEND-VV: asyncpg.DataError when '6091977' (str) was passed
    to a query expecting an integer.
    """
    mock_meme = {
        "id": 6091977,
        "type": "photo",
        "telegram_file_id": "some_file_id",
        "caption": None,
    }

    captured_params = {}

    async def fake_fetch_one(query, params):
        captured_params.update(params)
        return mock_meme

    mock_bot = MagicMock()
    mock_bot.send_photo = AsyncMock()

    with patch("src.tgbot.handlers.chat.agent.tools.fetch_one", side_effect=fake_fetch_one):
        with patch(
            "src.tgbot.handlers.chat.group_meme_reaction.build_meme_reaction_keyboard",
            return_value=None,
        ):
            from src.tgbot.handlers.chat.agent.tools import execute_send_meme

            await execute_send_meme(mock_bot, chat_id=123, meme_id="6091977")

    assert isinstance(captured_params["meme_id"], int), (
        "meme_id must be cast to int before SQL — asyncpg rejects str for integer columns"
    )
    assert captured_params["meme_id"] == 6091977


@pytest.mark.asyncio
async def test_dispatch_tool_send_meme_with_string_id():
    """dispatch_tool must not pass str meme_id to execute_send_meme."""
    mock_meme = {
        "id": 6091977,
        "type": "photo",
        "telegram_file_id": "some_file_id",
        "caption": None,
    }

    captured_params = {}

    async def fake_fetch_one(query, params):
        captured_params.update(params)
        return mock_meme

    mock_bot = MagicMock()
    mock_bot.send_photo = AsyncMock()

    with patch("src.tgbot.handlers.chat.agent.tools.fetch_one", side_effect=fake_fetch_one):
        with patch(
            "src.tgbot.handlers.chat.group_meme_reaction.build_meme_reaction_keyboard",
            return_value=None,
        ):
            from src.tgbot.handlers.chat.agent.tools import dispatch_tool

            result = await dispatch_tool(
                "send_meme",
                {"meme_id": "6091977"},
                mock_bot,
                chat_id=123,
            )

    assert "error" not in result.lower() or "not found" in result.lower() or "sent" in result.lower()
    assert isinstance(captured_params.get("meme_id"), int)
