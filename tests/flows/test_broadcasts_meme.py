import logging
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


@pytest.mark.asyncio
async def test_weekly_content_enrollment_respects_existing_silent_holdout(monkeypatch):
    monkeypatch.setattr(broadcast_meme.settings, "BROADCAST_CADENCE_HOLDOUT_ENABLED", True)
    monkeypatch.setattr(
        broadcast_meme, "get_user_ids_active_minutes_ago", AsyncMock(return_value=[11, 22, 33])
    )
    holdout = AsyncMock(return_value=[11, 33])
    dispatch = AsyncMock(side_effect=[RuntimeError("single-user failure"), "accepted"])
    monkeypatch.setattr(broadcast_meme, "drop_holdout", holdout)
    monkeypatch.setattr(broadcast_meme, "dispatch_opportunity", dispatch)
    monkeypatch.setattr(broadcast_meme.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(broadcast_meme, "get_run_logger", lambda: logging.getLogger())
    await broadcast_meme._broadcast_cadence_step("1w", 10080, 10140)
    holdout.assert_awaited_once_with("broadcast_cadence_holdout_v1_1w", [11, 22, 33], 20)
    assert [call.args[0] for call in dispatch.await_args_list] == [11, 33]
