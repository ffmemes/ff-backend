from unittest.mock import AsyncMock, MagicMock

import pytest
from agents.exceptions import MaxTurnsExceeded

from src.tgbot.handlers.chat.agent import runner


@pytest.mark.asyncio
async def test_run_chat_agent_handles_max_turns_as_fallback(monkeypatch):
    monkeypatch.setattr(runner.settings, "DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(runner, "get_latest_chat_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(runner, "_messages_to_text", MagicMock(return_value="user: ff memes?"))
    monkeypatch.setattr(runner, "get_tools", MagicMock(return_value=[]))
    monkeypatch.setattr(
        runner.Runner,
        "run",
        AsyncMock(side_effect=MaxTurnsExceeded("Max turns exceeded")),
    )
    warning = MagicMock()
    error = MagicMock()
    monkeypatch.setattr(runner.logger, "warning", warning)
    monkeypatch.setattr(runner.logger, "error", error)

    response = await runner.run_chat_agent(
        bot=object(),
        chat_id=123,
        user_id=456,
        reply_to_message_id=789,
    )

    assert response == runner.MAX_TURNS_FALLBACK_RESPONSE
    warning.assert_called_once()
    error.assert_not_called()
