from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from src.flows.storage import describe_memes_repository as repository


@pytest.mark.parametrize(
    "result, expected_raw_language",
    [
        ({"ocr_text": "visible text", "description": "a meme"}, ""),
        ({"ocr_text": "visible text", "description": "a meme", "language": None}, None),
        ({"ocr_text": "visible text", "description": "a meme", "language": 123}, 123),
    ],
)
@pytest.mark.asyncio
async def test_save_meme_description_ignores_missing_or_non_string_language(
    monkeypatch, result, expected_raw_language
):
    fetch_one = AsyncMock(return_value={})
    monkeypatch.setattr(repository, "fetch_one", fetch_one)
    result["__model"] = "test-model:free"

    merged = await repository.save_meme_description(
        42,
        {},
        result,
    )

    update_query = fetch_one.await_args.args[0]
    update_params = update_query.compile(dialect=postgresql.dialect()).params

    assert merged["raw_result"]["language"] == expected_raw_language
    assert "language_code" not in update_params


@pytest.mark.asyncio
async def test_save_meme_description_normalizes_known_string_language(monkeypatch):
    fetch_one = AsyncMock(return_value={})
    monkeypatch.setattr(repository, "fetch_one", fetch_one)

    await repository.save_meme_description(
        42,
        {},
        {
            "ocr_text": "visible text",
            "description": "a meme",
            "language": " RU ",
            "__model": "test-model:free",
        },
    )

    update_query = fetch_one.await_args.args[0]
    update_params = update_query.compile(dialect=postgresql.dialect()).params

    assert update_params["language_code"] == "ru"
