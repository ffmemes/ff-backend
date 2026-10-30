import asyncio
from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest, NetworkError

from src.storage.constants import MemeType
from src.storage.schemas import MemeData
from src.tgbot.senders import meme as meme_sender
from src.tgbot.senders.delivery import PreparedMemeDelivery
from src.tgbot.senders.meme import edit_last_message_with_meme, send_new_message_with_meme


def _prepared_delivery() -> PreparedMemeDelivery:
    return PreparedMemeDelivery(
        caption="<b>caption</b>",
        reply_markup=object(),  # type: ignore[arg-type]
        languages=frozenset({"en"}),
    )


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
async def test_send_meme_to_user_does_not_record_reaction_on_failed_delivery(monkeypatch):
    create_reaction = AsyncMock()

    async def send_meme(*_args):
        raise NetworkError("All connection attempts failed")

    monkeypatch.setattr(
        meme_sender,
        "get_user_info",
        AsyncMock(return_value={"interface_lang": "en", "nmemes_sent": 0}),
    )
    monkeypatch.setattr(
        meme_sender,
        "prepare_meme_delivery",
        AsyncMock(return_value=_prepared_delivery()),
    )
    monkeypatch.setattr(meme_sender, "send_new_message_with_meme", send_meme)
    monkeypatch.setattr(meme_sender, "create_user_meme_reaction", create_reaction)

    with pytest.raises(NetworkError):
        await meme_sender.send_meme_to_user(bot=object(), user_id=12001, meme=_meme())

    create_reaction.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_meme_to_user_does_not_record_reaction_on_rejected_delivery(
    monkeypatch,
):
    create_reaction = AsyncMock()

    monkeypatch.setattr(
        meme_sender,
        "get_user_info",
        AsyncMock(return_value={"interface_lang": "en", "nmemes_sent": 0}),
    )
    monkeypatch.setattr(
        meme_sender,
        "prepare_meme_delivery",
        AsyncMock(return_value=_prepared_delivery()),
    )
    monkeypatch.setattr(meme_sender, "send_new_message_with_meme", AsyncMock(return_value=None))
    monkeypatch.setattr(meme_sender, "create_user_meme_reaction", create_reaction)

    await meme_sender.send_meme_to_user(bot=object(), user_id=12001, meme=_meme())

    create_reaction.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_meme_to_user_continues_recording_after_cancellation(monkeypatch):
    calls: list[str] = []
    reaction_started = asyncio.Event()
    reaction_finished = asyncio.Event()
    reaction_can_finish = asyncio.Event()

    async def create_reaction(*_args):
        calls.append("create_reaction_started")
        reaction_started.set()
        await reaction_can_finish.wait()
        calls.append("create_reaction_finished")
        reaction_finished.set()

    async def send_meme(*_args):
        calls.append("send_meme")
        return object()

    monkeypatch.setattr(
        meme_sender,
        "get_user_info",
        AsyncMock(return_value={"interface_lang": "en", "nmemes_sent": 0}),
    )
    monkeypatch.setattr(
        meme_sender,
        "prepare_meme_delivery",
        AsyncMock(return_value=_prepared_delivery()),
    )
    monkeypatch.setattr(meme_sender, "send_new_message_with_meme", send_meme)
    monkeypatch.setattr(meme_sender, "create_user_meme_reaction", create_reaction)

    send_task = asyncio.create_task(
        meme_sender.send_meme_to_user(bot=object(), user_id=12001, meme=_meme())
    )
    await reaction_started.wait()

    send_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(send_task, timeout=0.1)

    assert calls == ["send_meme", "create_reaction_started"]

    reaction_can_finish.set()
    await asyncio.wait_for(reaction_finished.wait(), timeout=0.1)

    assert calls == ["send_meme", "create_reaction_started", "create_reaction_finished"]
