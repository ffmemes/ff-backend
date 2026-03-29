"""Regression tests for chat agent tool dispatch."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agents.tool import ToolContext

from src.tgbot.handlers.chat.agent.runner import ChatAgentContext


def _make_tool_ctx(bot=None, chat_id=123, user_id=1):
    """Build a ToolContext wrapping a ChatAgentContext for tool tests."""
    if bot is None:
        bot = MagicMock()
        bot.send_photo = AsyncMock()
    ctx = ChatAgentContext(bot=bot, chat_id=chat_id, user_id=user_id)
    return ToolContext(context=ctx, tool_name="test", tool_call_id="test")


@pytest.mark.asyncio
async def test_send_meme_coerces_string_meme_id():
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

    tool_ctx = _make_tool_ctx(bot=mock_bot)

    with patch("src.tgbot.handlers.chat.agent.tools.fetch_one", side_effect=fake_fetch_one):
        with patch(
            "src.tgbot.handlers.chat.group_meme_reaction.build_meme_reaction_keyboard",
            return_value=None,
        ):
            from src.tgbot.handlers.chat.agent.tools import send_meme

            # LLM sends meme_id as string in JSON — must be coerced to int
            result = await send_meme.on_invoke_tool(tool_ctx, json.dumps({"meme_id": "6091977"}))

    assert isinstance(captured_params["meme_id"], int), (
        "meme_id must be cast to int before SQL — asyncpg rejects str for integer columns"
    )
    assert captured_params["meme_id"] == 6091977
    assert "Sent" in result
