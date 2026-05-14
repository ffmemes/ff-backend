from unittest.mock import AsyncMock

import pytest

from src.flows.storage import memes


@pytest.mark.asyncio
async def test_process_cached_telegram_source_promotes_uploaded_memes(monkeypatch):
    etl = AsyncMock()
    get_unloaded = AsyncMock(return_value=[{"id": 1}])
    process_unloaded = AsyncMock()
    promote_ready = AsyncMock(return_value=[{"id": 1, "status": "ok"}])

    monkeypatch.setattr(memes, "etl_memes_from_raw_telegram_posts", etl)
    monkeypatch.setattr(memes, "get_unloaded_tg_memes", get_unloaded)
    monkeypatch.setattr(memes, "_process_unloaded_memes", process_unloaded)
    monkeypatch.setattr(memes, "update_meme_status_of_ready_memes", promote_ready)

    await memes.process_cached_telegram_source(42, limit=5)

    etl.assert_awaited_once_with([42], fresh_only=False)
    get_unloaded.assert_awaited_once_with(
        limit=5,
        meme_source_ids=[42],
        fresh_only=False,
    )
    process_unloaded.assert_awaited_once_with(
        [{"id": 1}],
        "prepared Telegram source",
    )
    promote_ready.assert_awaited_once()
