from unittest.mock import AsyncMock, MagicMock

import pytest

from src.storage.constants import MemeType
from src.storage.schemas import MemeData
from src.tgbot.senders import delivery


@pytest.mark.asyncio
async def test_prepare_meme_delivery_builds_keyboard_and_caption(monkeypatch):
    meme = MemeData(
        id=42,
        type=MemeType.IMAGE,
        telegram_file_id="file-id",
        caption="hello",
        recommended_by="test",
        nlikes=7,
    )
    user_info = {"interface_lang": "en", "type": "user", "nmemes_sent": 10}

    monkeypatch.setattr(
        delivery,
        "collect_user_languages",
        AsyncMock(return_value={"en"}),
    )
    monkeypatch.setattr(delivery, "get_meme_share_button_text", lambda lang: "Share")
    monkeypatch.setattr(
        delivery,
        "get_or_assign_meme_share_button_variant",
        AsyncMock(return_value="url_share"),
    )
    monkeypatch.setattr(
        delivery,
        "get_visible_meme_like_count",
        AsyncMock(return_value=None),
    )
    keyboard = MagicMock(name="keyboard")
    monkeypatch.setattr(delivery, "meme_reaction_keyboard", lambda *a, **k: keyboard)
    monkeypatch.setattr(
        delivery,
        "get_meme_caption_for_user_id",
        AsyncMock(return_value="caption with link"),
    )

    prepared = await delivery.prepare_meme_delivery(
        user_id=1001,
        meme=meme,
        user_info=user_info,
        reaction_context="onboard",
    )

    assert prepared.caption == "caption with link"
    assert prepared.reply_markup is keyboard
    assert prepared.share_button_variant == "url_share"
    assert prepared.languages == frozenset({"en"})
