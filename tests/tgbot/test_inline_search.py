import pytest

from src.storage.constants import MemeType
from src.tgbot import service
from src.tgbot.handlers.inline import (
    INLINE_SEARCH_RESULT_LIMIT,
    build_inline_meme_result,
    parse_exact_meme_inline_query,
)


def test_inline_search_returns_twenty_results():
    assert INLINE_SEARCH_RESULT_LIMIT == 20


def test_parse_exact_meme_inline_query():
    assert parse_exact_meme_inline_query("#123") == 123
    assert parse_exact_meme_inline_query("#00123") == 123
    assert parse_exact_meme_inline_query("123") is None
    assert parse_exact_meme_inline_query("#abc") is None


def test_build_exact_inline_meme_result_uses_share_deep_link():
    result = build_inline_meme_result(
        {
            "id": 123,
            "type": MemeType.IMAGE.value,
            "telegram_file_id": "photo-file-id",
        },
        {"id": 456},
    )

    assert result.id == "123"
    assert result.photo_file_id == "photo-file-id"
    assert "start=s_456_123" in result.caption


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
    assert "ILIKE :search_pattern ESCAPE '\\'" in captured["query"]
    assert "% :search_query" in captured["query"]
    assert "LEFT JOIN meme_stats MS" in captured["query"]
    assert "AS inline_quality_score" in captured["query"]
    assert "(COALESCE(MS.nlikes, 0) + 1.)" in captured["query"]
    assert "COALESCE(MS.nlikes, 0) + COALESCE(MS.ndislikes, 0) + 2" in captured["query"]
    assert "NULLIF(MS.nlikes + MS.ndislikes + 1, 0)" not in captured["query"]
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


@pytest.mark.asyncio
async def test_inline_search_escapes_like_wildcards(monkeypatch):
    captured = {}

    async def fake_fetch_all(query, params=None):
        captured["params"] = params
        return []

    monkeypatch.setattr(service, "fetch_all", fake_fetch_all)

    await service.search_memes_for_inline_query(r"%%_\\", limit=10)

    assert captured["params"]["search_query"] == r"%%_\\"
    assert captured["params"]["search_pattern"] == r"%\%\%\_\\\\%"
