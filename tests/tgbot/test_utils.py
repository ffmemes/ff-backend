from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest

from src.tgbot.utils import remove_buttons_with_callback, safe_answer_callback_query


def test_remove_buttons_with_callback_drops_empty_rows_and_inline_switch_buttons():
    reply_markup = {
        "inline_keyboard": [
            [
                {
                    "text": "Share inline",
                    "switch_inline_query_chosen_chat": {"query": "#123"},
                }
            ],
            [
                {"text": "Like", "callback_data": "r:123:1"},
                {"text": "Skip", "callback_data": "r:123:2"},
            ],
            [{"text": "Open", "url": "https://t.me/ffmemesbot?start=s_1_123"}],
        ]
    }

    assert remove_buttons_with_callback(reply_markup) == {
        "inline_keyboard": [[{"text": "Open", "url": "https://t.me/ffmemesbot?start=s_1_123"}]]
    }


@pytest.mark.asyncio
async def test_safe_answer_callback_query_ignores_stale_query():
    callback_query = SimpleNamespace(
        answer=AsyncMock(side_effect=BadRequest("Query is too old and response timeout expired"))
    )

    await safe_answer_callback_query(callback_query, "ok")

    callback_query.answer.assert_awaited_once_with("ok")


@pytest.mark.asyncio
async def test_safe_answer_callback_query_reraises_other_bad_request():
    callback_query = SimpleNamespace(answer=AsyncMock(side_effect=BadRequest("other error")))

    with pytest.raises(BadRequest):
        await safe_answer_callback_query(callback_query)
