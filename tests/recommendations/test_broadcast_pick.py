"""Unit tests for retention-broadcast HQ meme picker."""

from unittest.mock import AsyncMock, patch

import pytest

from src.recommendations.broadcast_pick import (
    BROADCAST_HQ_RECOMMENDED_BY,
    BROADCAST_RECOMMENDED_BY,
    pick_reengagement_meme,
)
from src.storage.constants import MemeType
from src.storage.schemas import MemeData


@pytest.mark.asyncio
async def test_hq_pick_uses_sql_row_and_hq_label(monkeypatch):
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
