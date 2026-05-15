import pytest

from src.tgbot import service
from src.tgbot.handlers.inline import INLINE_SEARCH_RESULT_LIMIT


def test_inline_search_returns_twenty_results():
    assert INLINE_SEARCH_RESULT_LIMIT == 20


@pytest.mark.asyncio
async def test_inline_search_uses_old_new_ocr_and_openrouter_description(monkeypatch):
    captured = {}

    async def fake_fetch_all(query, params=None):
        captured["query"] = str(query)
        captured["params"] = params
        return [{"id": 1}]

    monkeypatch.setattr(service, "fetch_all", fake_fetch_all)

    rows = await service.search_memes_for_inline_query("деньги", limit=10)

    assert rows == [{"id": 1}]
    assert "ocr_result ->> 'text'" in captured["query"]
    assert "ocr_result -> 'raw_result' ->> 'ocr_text'" in captured["query"]
    assert "ocr_result ->> 'description'" in captured["query"]
    assert "ILIKE :search_pattern" in captured["query"]
    assert "% :search_query" in captured["query"]
    assert "LEFT JOIN meme_stats MS" in captured["query"]
    assert "AS inline_quality_score" in captured["query"]
    assert "ORDER BY inline_search_score DESC, inline_quality_score DESC" in captured["query"]
    assert captured["params"] == {
        "search_query": "деньги",
        "search_pattern": "%деньги%",
        "status": "ok",
        "type": "image",
        "limit": 10,
    }


@pytest.mark.asyncio
async def test_inline_search_clamps_limit(monkeypatch):
    captured = {}

    async def fake_fetch_all(query, params=None):
        captured["params"] = params
        return []

    monkeypatch.setattr(service, "fetch_all", fake_fetch_all)

    await service.search_memes_for_inline_query("money", limit=1000)

    assert captured["params"]["limit"] == 50
