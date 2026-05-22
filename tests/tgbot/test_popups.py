from unittest.mock import AsyncMock

import pytest
from telegram import InlineKeyboardMarkup

from src.tgbot.schemas import Popup
from src.tgbot.senders import popups


def _popup(popup_id: str, _user_info: dict) -> Popup:
    return Popup(id=popup_id, text=popup_id, reply_markup=InlineKeyboardMarkup([]))


@pytest.mark.asyncio
async def test_upload_promo_treatment_precedes_ten_memes_achievement(monkeypatch):
    monkeypatch.setattr(popups, "_get_popup", _popup)
    monkeypatch.setattr(popups, "safe_emit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(popups, "get_experiment_variant", AsyncMock(return_value=None))
    monkeypatch.setattr(popups, "assign_experiment", AsyncMock(return_value=True))
    monkeypatch.setattr(popups, "user_popup_already_sent", AsyncMock(return_value=False))

    popup = await popups.get_popup_to_send(12002, {"nmemes_sent": 10, "interface_lang": "ru"})

    assert popup is not None
    assert popup.id == popups.UPLOAD_PROMO_DAY1_POPUP_ID


@pytest.mark.asyncio
async def test_ten_memes_achievement_can_follow_sent_upload_promo(monkeypatch):
    async def already_sent(_user_id: int, popup_id: str) -> bool:
        return popup_id == popups.UPLOAD_PROMO_DAY1_POPUP_ID

    monkeypatch.setattr(popups, "_get_popup", _popup)
    monkeypatch.setattr(popups, "safe_emit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(popups, "get_experiment_variant", AsyncMock(return_value="treatment"))
    monkeypatch.setattr(popups, "user_popup_already_sent", already_sent)

    popup = await popups.get_popup_to_send(12002, {"nmemes_sent": 10, "interface_lang": "ru"})

    assert popup is not None
    assert popup.id == "achievement.nmemes_sent_10"
