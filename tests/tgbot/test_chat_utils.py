from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest

from src.tgbot.handlers.chat.utils import _reply_and_delete


@pytest.mark.asyncio
async def test_reply_and_delete_falls_back_when_reply_message_is_missing():
    sent_message = AsyncMock()
    message = AsyncMock()
    message.reply_text.side_effect = [
        BadRequest("Message to be replied not found"),
        sent_message,
    ]

    await _reply_and_delete(message, "temporary warning", sleep_sec=0)

    assert message.reply_text.await_args_list[0].kwargs == {"reply_markup": None}
    assert message.reply_text.await_args_list[1].kwargs == {
        "reply_markup": None,
        "do_quote": False,
    }
    sent_message.delete.assert_awaited_once()
    message.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_reply_and_delete_reraises_unrelated_bad_request():
    message = AsyncMock()
    message.reply_text.side_effect = BadRequest("Chat not found")

    with pytest.raises(BadRequest):
        await _reply_and_delete(message, "temporary warning", sleep_sec=0)
