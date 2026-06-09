from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest, NetworkError

from src.storage.constants import MemeType
from src.storage.schemas import MemeData
from src.tgbot.senders import meme as meme_sender
from src.tgbot.senders.meme import edit_last_message_with_meme, send_new_message_with_meme


def _meme() -> MemeData:
    return MemeData(
        id=123,
        type=MemeType.IMAGE,
        telegram_file_id="photo-file-id",
        caption="<b>caption</b>",
    )


@pytest.mark.asyncio
async def test_edit_last_message_retries_transient_edit_media_error(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("src.tgbot.telegram_retry.asyncio.sleep", sleep)

    class Message:
        def __init__(self) -> None:
            self.edit_media_calls = 0

        async def edit_media(self, **_kwargs):
            self.edit_media_calls += 1
            if self.edit_media_calls == 1:
                raise NetworkError("Server disconnected without sending a response")

        async def edit_caption(self, **_kwargs):
            return "edited"

    message = Message()

    result = await edit_last_message_with_meme(message, _meme())

    assert result == "edited"
    assert message.edit_media_calls == 2
    sleep.assert_awaited_once()


@pytest.mark.asyncio
async def test_edit_last_message_treats_not_modified_as_success():
    class Message:
        async def edit_media(self, **_kwargs):
            raise BadRequest(
                "Message is not modified: specified new message content and reply markup "
                "are exactly the same"
            )

        async def edit_caption(self, **_kwargs):
            return self

    message = Message()

    result = await edit_last_message_with_meme(message, _meme())

    assert result is message


@pytest.mark.asyncio
async def test_send_new_message_does_not_retry_ambiguous_transport_error(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("src.tgbot.telegram_retry.asyncio.sleep", sleep)

    class Bot:
        def __init__(self) -> None:
            self.send_photo_calls = 0

        async def send_photo(self, **_kwargs):
            self.send_photo_calls += 1
            raise NetworkError("All connection attempts failed")

    bot = Bot()

    with pytest.raises(NetworkError):
        await send_new_message_with_meme(bot, 12001, _meme())

    assert bot.send_photo_calls == 1
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_meme_to_user_awaits_first_meme_nudge_after_reaction(monkeypatch):
    calls: list[str] = []

    async def assign_nudge(_user_id: int) -> str:
        calls.append("assign_nudge")
        return "treatment"

    async def create_reaction(*_args):
        calls.append("create_reaction")

    async def send_nudge(*_args):
        calls.append("send_nudge")

    monkeypatch.setattr(
        meme_sender,
        "get_user_info",
        AsyncMock(return_value={"interface_lang": "en", "nmemes_sent": 0}),
    )
    monkeypatch.setattr(meme_sender, "collect_user_languages", AsyncMock(return_value={"en"}))
    monkeypatch.setattr(meme_sender, "get_meme_share_button_text", lambda _lang: "Share")
    monkeypatch.setattr(
        meme_sender,
        "get_or_assign_meme_share_button_variant",
        AsyncMock(return_value="url_share"),
    )
    monkeypatch.setattr(meme_sender, "get_visible_meme_like_count", AsyncMock(return_value=0))
    monkeypatch.setattr(
        meme_sender,
        "meme_reaction_keyboard",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        meme_sender,
        "get_meme_caption_for_user_id",
        AsyncMock(return_value="<b>caption</b>"),
    )
    monkeypatch.setattr(meme_sender, "send_new_message_with_meme", AsyncMock())
    monkeypatch.setattr(meme_sender, "get_or_assign_first_meme_nudge_variant", assign_nudge)
    monkeypatch.setattr(meme_sender, "create_user_meme_reaction", create_reaction)
    monkeypatch.setattr(meme_sender, "maybe_send_first_meme_nudge", send_nudge)

    await meme_sender.send_meme_to_user(bot=object(), user_id=12001, meme=_meme())

    assert calls == ["assign_nudge", "create_reaction", "send_nudge"]


@pytest.mark.asyncio
async def test_send_meme_to_user_skips_first_meme_nudge_for_returning_user(monkeypatch):
    monkeypatch.setattr(
        meme_sender,
        "get_user_info",
        AsyncMock(return_value={"interface_lang": "en", "nmemes_sent": 2}),
    )
    monkeypatch.setattr(meme_sender, "collect_user_languages", AsyncMock(return_value={"en"}))
    monkeypatch.setattr(meme_sender, "get_meme_share_button_text", lambda _lang: "Share")
    monkeypatch.setattr(
        meme_sender,
        "get_or_assign_meme_share_button_variant",
        AsyncMock(return_value="url_share"),
    )
    monkeypatch.setattr(meme_sender, "get_visible_meme_like_count", AsyncMock(return_value=0))
    monkeypatch.setattr(
        meme_sender,
        "meme_reaction_keyboard",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        meme_sender,
        "get_meme_caption_for_user_id",
        AsyncMock(return_value="<b>caption</b>"),
    )
    monkeypatch.setattr(meme_sender, "send_new_message_with_meme", AsyncMock())
    assign_nudge = AsyncMock()
    monkeypatch.setattr(meme_sender, "get_or_assign_first_meme_nudge_variant", assign_nudge)
    monkeypatch.setattr(meme_sender, "create_user_meme_reaction", AsyncMock())

    await meme_sender.send_meme_to_user(bot=object(), user_id=12001, meme=_meme())

    assign_nudge.assert_not_awaited()
