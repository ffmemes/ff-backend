from unittest.mock import AsyncMock

import pytest

from src.flows.broadcasts import meme as broadcast_meme
from src.storage.constants import MemeType
from src.storage.schemas import MemeData


@pytest.mark.asyncio
async def test_send_to_user_uses_picker_label(monkeypatch):
    meme = MemeData(
        id=55,
        type=MemeType.IMAGE,
        telegram_file_id="tg",
        caption=None,
        recommended_by="broadcast_reengagement_hq",
    )
    send = AsyncMock()
    pick = AsyncMock(return_value=(meme, "broadcast_reengagement_hq"))
    monkeypatch.setattr(broadcast_meme, "pick_reengagement_meme", pick)
    monkeypatch.setattr(broadcast_meme, "send_meme_to_user", send)
    monkeypatch.setattr(broadcast_meme, "bot", object())

    await broadcast_meme._send_to_user(99)

    pick.assert_awaited_once_with(99)
    assert send.await_args.kwargs["recommended_by"] == "broadcast_reengagement_hq"
