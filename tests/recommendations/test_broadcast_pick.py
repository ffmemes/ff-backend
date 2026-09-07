"""Unit tests for retention-broadcast HQ meme picker."""

from unittest.mock import AsyncMock, patch

import pytest

from src.recommendations.broadcast_pick import (
    BROADCAST_CHANNEL_VIRAL_RECOMMENDED_BY,
    BROADCAST_HQ_RECOMMENDED_BY,
    BROADCAST_RECOMMENDED_BY,
    pick_reengagement_meme,
)
from src.storage.constants import MemeType
from src.storage.schemas import MemeData


def _disable_channel_viral(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.recommendations.broadcast_pick.settings.BROADCAST_CHANNEL_VIRAL_PICK_ENABLED",
        False,
    )


@pytest.mark.asyncio
async def test_hq_pick_uses_sql_row_and_hq_label(monkeypatch):
    _disable_channel_viral(monkeypatch)
    monkeypatch.setattr(
        "src.recommendations.broadcast_pick.settings.BROADCAST_HIGH_QUALITY_PICK_ENABLED",
        True,
    )
    row = {
        "id": 42,
        "type": MemeType.IMAGE,
        "telegram_file_id": "file-42",
        "caption": "hi",
        "nlikes": 99,
    }
    with patch(
        "src.recommendations.broadcast_pick.fetch_one",
        new_callable=AsyncMock,
        return_value=row,
    ) as fetch_one:
        meme, label = await pick_reengagement_meme(7)

    fetch_one.assert_awaited_once()
    assert label == BROADCAST_HQ_RECOMMENDED_BY
    assert meme is not None
    assert meme.id == 42
    assert meme.recommended_by == BROADCAST_HQ_RECOMMENDED_BY


@pytest.mark.asyncio
async def test_hq_empty_falls_back_to_queue(monkeypatch):
    _disable_channel_viral(monkeypatch)
    monkeypatch.setattr(
        "src.recommendations.broadcast_pick.settings.BROADCAST_HIGH_QUALITY_PICK_ENABLED",
        True,
    )
    queue_meme = MemeData(
        id=9,
        type=MemeType.IMAGE,
        telegram_file_id="q",
        caption=None,
        recommended_by="lr_smoothed",
    )
    with (
        patch(
            "src.recommendations.broadcast_pick.fetch_one",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.recommendations.broadcast_pick.check_queue",
            new_callable=AsyncMock,
        ) as check_queue,
        patch(
            "src.recommendations.broadcast_pick.get_next_meme_for_user",
            new_callable=AsyncMock,
            return_value=queue_meme,
        ) as get_next,
    ):
        meme, label = await pick_reengagement_meme(7)

    check_queue.assert_awaited_once_with(7)
    get_next.assert_awaited_once_with(7)
    assert meme is queue_meme
    assert label == BROADCAST_RECOMMENDED_BY


@pytest.mark.asyncio
async def test_hq_disabled_uses_queue_only(monkeypatch):
    _disable_channel_viral(monkeypatch)
    monkeypatch.setattr(
        "src.recommendations.broadcast_pick.settings.BROADCAST_HIGH_QUALITY_PICK_ENABLED",
        False,
    )
    queue_meme = MemeData(
        id=3,
        type=MemeType.IMAGE,
        telegram_file_id="q",
        caption=None,
        recommended_by="goat",
    )
    with (
        patch(
            "src.recommendations.broadcast_pick.fetch_one",
            new_callable=AsyncMock,
        ) as fetch_one,
        patch(
            "src.recommendations.broadcast_pick.check_queue",
            new_callable=AsyncMock,
        ),
        patch(
            "src.recommendations.broadcast_pick.get_next_meme_for_user",
            new_callable=AsyncMock,
            return_value=queue_meme,
        ),
    ):
        meme, label = await pick_reengagement_meme(1)

    fetch_one.assert_not_called()
    assert meme is queue_meme
    assert label == BROADCAST_RECOMMENDED_BY


@pytest.mark.asyncio
async def test_channel_viral_pick_wins_over_hq(monkeypatch):
    monkeypatch.setattr(
        "src.recommendations.broadcast_pick.settings.BROADCAST_CHANNEL_VIRAL_PICK_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "src.recommendations.broadcast_pick.settings.BROADCAST_HIGH_QUALITY_PICK_ENABLED",
        True,
    )
    row = {
        "id": 10084067,
        "type": MemeType.IMAGE,
        "telegram_file_id": "viral-file",
        "caption": None,
        "nlikes": 12,
    }
    with patch(
        "src.recommendations.broadcast_pick.fetch_one",
        new_callable=AsyncMock,
        return_value=row,
    ) as fetch_one:
        meme, label = await pick_reengagement_meme(7)

    fetch_one.assert_awaited_once()
    assert label == BROADCAST_CHANNEL_VIRAL_RECOMMENDED_BY
    assert meme is not None
    assert meme.id == 10084067
    assert meme.recommended_by == BROADCAST_CHANNEL_VIRAL_RECOMMENDED_BY


@pytest.mark.asyncio
async def test_channel_viral_empty_falls_back_to_hq(monkeypatch):
    monkeypatch.setattr(
        "src.recommendations.broadcast_pick.settings.BROADCAST_CHANNEL_VIRAL_PICK_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "src.recommendations.broadcast_pick.settings.BROADCAST_HIGH_QUALITY_PICK_ENABLED",
        True,
    )
    hq_row = {
        "id": 42,
        "type": MemeType.IMAGE,
        "telegram_file_id": "file-42",
        "caption": "hi",
        "nlikes": 99,
    }
    with patch(
        "src.recommendations.broadcast_pick.fetch_one",
        new_callable=AsyncMock,
        side_effect=[None, hq_row],
    ) as fetch_one:
        meme, label = await pick_reengagement_meme(7)

    assert fetch_one.await_count == 2
    assert label == BROADCAST_HQ_RECOMMENDED_BY
    assert meme is not None
    assert meme.id == 42
