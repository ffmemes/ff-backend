from unittest.mock import AsyncMock

import pytest
from telegram import InlineKeyboardMarkup

from src.tgbot.schemas import Popup
from src.tgbot.senders import popups


def _popup(popup_id: str, _user_info: dict) -> Popup:
    return Popup(id=popup_id, text=popup_id, reply_markup=InlineKeyboardMarkup([]))


@pytest.mark.asyncio
async def test_ten_memes_achievement_popup(monkeypatch):
    monkeypatch.setattr(popups, "_get_popup", _popup)
    monkeypatch.setattr(popups, "user_popup_already_sent", AsyncMock(return_value=False))

    popup = await popups.get_popup_to_send(12002, {"nmemes_sent": 10, "interface_lang": "ru"})

    assert popup is not None
    assert popup.id == "achievement.nmemes_sent_10"
