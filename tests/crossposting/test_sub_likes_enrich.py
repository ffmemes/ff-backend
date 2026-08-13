"""Channel-subscriber like counts on ranker candidates (shadow)."""

from unittest.mock import AsyncMock

import pytest

from src.crossposting import service as xpost
from src.tgbot.constants import TELEGRAM_CHANNEL_RU_CHAT_ID


@pytest.mark.asyncio
async def test_enrich_sub_likes(monkeypatch):
    monkeypatch.setattr(
        xpost,
        "fetch_all",
        AsyncMock(return_value=[{"meme_id": 1, "n_sub": 7}]),
    )
    rows = [{"id": 1}, {"id": 2}]
    out = await xpost._enrich_candidates_with_sub_likes(rows, channel="tgchannelru")
    assert out[0]["n_sub_likes"] == 7
    assert out[1]["n_sub_likes"] == 0
    # ensure we queried with RU chat id
    call_kw = xpost.fetch_all.await_args
    assert call_kw[0][1]["chat_id"] == TELEGRAM_CHANNEL_RU_CHAT_ID


@pytest.mark.asyncio
async def test_enrich_sub_likes_empty(monkeypatch):
    out = await xpost._enrich_candidates_with_sub_likes([], channel="tgchannelru")
    assert out == []
