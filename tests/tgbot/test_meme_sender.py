from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest, NetworkError

from src.storage.constants import MemeType
from src.storage.schemas import MemeData
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
async def test_send_new_message_retries_transient_send_error(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("src.tgbot.telegram_retry.asyncio.sleep", sleep)

    class Bot:
        def __init__(self) -> None:
            self.send_photo_calls = 0

        async def send_photo(self, **_kwargs):
            self.send_photo_calls += 1
            if self.send_photo_calls == 1:
                raise NetworkError("All connection attempts failed")
            return "sent"

    bot = Bot()

    result = await send_new_message_with_meme(bot, 12001, _meme())

    assert result == "sent"
    assert bot.send_photo_calls == 2
    sleep.assert_awaited_once()
