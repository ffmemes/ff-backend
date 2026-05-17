from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest

from src.tgbot.utils import safe_answer_callback_query


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
