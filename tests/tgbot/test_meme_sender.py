import asyncio
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
async def test_send_meme_to_user_assigns_first_meme_nudge_after_delivery(monkeypatch):
    calls: list[str] = []

    async def first_meme_nudge_variant(_user_id: int, *, is_first_meme: bool) -> str:
        assert is_first_meme is True
        calls.append("assign_nudge")
        return "treatment"

    async def create_reaction(*_args):
        calls.append("create_reaction")

    async def send_nudge(*_args):
        calls.append("send_nudge")

    async def send_meme(*_args):
        calls.append("send_meme")
        return object()

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
    monkeypatch.setattr(meme_sender, "send_new_message_with_meme", send_meme)
    monkeypatch.setattr(
        meme_sender,
        "get_first_meme_nudge_variant_to_send",
        first_meme_nudge_variant,
    )
    monkeypatch.setattr(meme_sender, "create_user_meme_reaction", create_reaction)
    monkeypatch.setattr(meme_sender, "maybe_send_first_meme_nudge", send_nudge)

    await meme_sender.send_meme_to_user(bot=object(), user_id=12001, meme=_meme())

    assert calls == ["send_meme", "assign_nudge", "create_reaction", "send_nudge"]


@pytest.mark.asyncio
async def test_send_meme_to_user_does_not_assign_first_meme_nudge_on_failed_delivery(monkeypatch):
    nudge_variant = AsyncMock(return_value="treatment")
    create_reaction = AsyncMock()
    send_nudge = AsyncMock()

    async def send_meme(*_args):
        raise NetworkError("All connection attempts failed")

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
    monkeypatch.setattr(meme_sender, "send_new_message_with_meme", send_meme)
    monkeypatch.setattr(
        meme_sender,
        "get_first_meme_nudge_variant_to_send",
        nudge_variant,
    )
    monkeypatch.setattr(meme_sender, "create_user_meme_reaction", create_reaction)
    monkeypatch.setattr(meme_sender, "maybe_send_first_meme_nudge", send_nudge)

    with pytest.raises(NetworkError):
        await meme_sender.send_meme_to_user(bot=object(), user_id=12001, meme=_meme())

    nudge_variant.assert_not_awaited()
    create_reaction.assert_not_awaited()
    send_nudge.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_meme_to_user_does_not_assign_first_meme_nudge_on_rejected_delivery(
    monkeypatch,
):
    nudge_variant = AsyncMock(return_value="treatment")
    create_reaction = AsyncMock()
    send_nudge = AsyncMock()

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
    monkeypatch.setattr(meme_sender, "send_new_message_with_meme", AsyncMock(return_value=None))
    monkeypatch.setattr(
        meme_sender,
        "get_first_meme_nudge_variant_to_send",
        nudge_variant,
    )
    monkeypatch.setattr(meme_sender, "create_user_meme_reaction", create_reaction)
    monkeypatch.setattr(meme_sender, "maybe_send_first_meme_nudge", send_nudge)

    await meme_sender.send_meme_to_user(bot=object(), user_id=12001, meme=_meme())

    nudge_variant.assert_not_awaited()
    create_reaction.assert_not_awaited()
    send_nudge.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_meme_to_user_records_delivery_after_nudge_assignment_error(
    monkeypatch,
):
    calls: list[str] = []

    async def first_meme_nudge_variant(_user_id: int, *, is_first_meme: bool) -> str:
        assert is_first_meme is True
        calls.append("assign_nudge")
        raise RuntimeError("experiment storage unavailable")

    async def create_reaction(*_args):
        calls.append("create_reaction")

    async def send_meme(*_args):
        calls.append("send_meme")
        return object()

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
    monkeypatch.setattr(meme_sender, "send_new_message_with_meme", send_meme)
    monkeypatch.setattr(
        meme_sender,
        "get_first_meme_nudge_variant_to_send",
        first_meme_nudge_variant,
    )
    monkeypatch.setattr(meme_sender, "create_user_meme_reaction", create_reaction)

    with pytest.raises(RuntimeError, match="experiment storage unavailable"):
        await meme_sender.send_meme_to_user(bot=object(), user_id=12001, meme=_meme())

    assert calls == ["send_meme", "assign_nudge", "create_reaction"]


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
    monkeypatch.setattr(meme_sender, "send_new_message_with_meme", send_meme)
    monkeypatch.setattr(
        meme_sender,
        "get_first_meme_nudge_variant_to_send",
        AsyncMock(return_value=None),
    )
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


@pytest.mark.asyncio
async def test_send_meme_to_user_continues_post_delivery_after_nudge_assignment_cancellation(
    monkeypatch,
):
    calls: list[str] = []
    nudge_assignment_started = asyncio.Event()
    nudge_assignment_finished = asyncio.Event()
    nudge_assignment_can_finish = asyncio.Event()
    reaction_finished = asyncio.Event()

    async def first_meme_nudge_variant(_user_id: int, *, is_first_meme: bool) -> None:
        assert is_first_meme is True
        calls.append("assign_nudge_started")
        nudge_assignment_started.set()
        await nudge_assignment_can_finish.wait()
        calls.append("assign_nudge_finished")
        nudge_assignment_finished.set()
        return None

    async def create_reaction(*_args):
        calls.append("create_reaction")
        reaction_finished.set()

    async def send_meme(*_args):
        calls.append("send_meme")
        return object()

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
    monkeypatch.setattr(meme_sender, "send_new_message_with_meme", send_meme)
    monkeypatch.setattr(
        meme_sender,
        "get_first_meme_nudge_variant_to_send",
        first_meme_nudge_variant,
    )
    monkeypatch.setattr(meme_sender, "create_user_meme_reaction", create_reaction)

    send_task = asyncio.create_task(
        meme_sender.send_meme_to_user(bot=object(), user_id=12001, meme=_meme())
    )
    await nudge_assignment_started.wait()

    send_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(send_task, timeout=0.1)

    assert calls == ["send_meme", "assign_nudge_started"]

    nudge_assignment_can_finish.set()
    await asyncio.wait_for(nudge_assignment_finished.wait(), timeout=0.1)
    await asyncio.wait_for(reaction_finished.wait(), timeout=0.1)

    assert calls == [
        "send_meme",
        "assign_nudge_started",
        "assign_nudge_finished",
        "create_reaction",
    ]


@pytest.mark.asyncio
async def test_send_meme_to_user_can_defer_first_meme_nudge_after_reaction(monkeypatch):
    calls: list[str] = []
    nudge_can_finish = asyncio.Event()

    async def first_meme_nudge_variant(_user_id: int, *, is_first_meme: bool) -> str:
        assert is_first_meme is True
        calls.append("assign_nudge")
        return "treatment"

    async def create_reaction(*_args):
        calls.append("create_reaction")

    async def send_nudge(*_args):
        calls.append("send_nudge_started")
        await nudge_can_finish.wait()
        calls.append("send_nudge_finished")

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
    monkeypatch.setattr(
        meme_sender,
        "get_first_meme_nudge_variant_to_send",
        first_meme_nudge_variant,
    )
    monkeypatch.setattr(meme_sender, "create_user_meme_reaction", create_reaction)
    monkeypatch.setattr(meme_sender, "maybe_send_first_meme_nudge", send_nudge)

    nudge_tasks: list[asyncio.Task[None]] = []
    await asyncio.wait_for(
        meme_sender.send_meme_to_user(
            bot=object(),
            user_id=12001,
            meme=_meme(),
            first_meme_nudge_tasks=nudge_tasks,
        ),
        timeout=0.1,
    )
    await asyncio.sleep(0)

    assert calls == ["assign_nudge", "create_reaction", "send_nudge_started"]
    assert len(nudge_tasks) == 2
    assert nudge_tasks[0].done()
    assert not nudge_tasks[1].done()

    nudge_can_finish.set()
    await nudge_tasks[1]
    assert calls == [
        "assign_nudge",
        "create_reaction",
        "send_nudge_started",
        "send_nudge_finished",
    ]


@pytest.mark.asyncio
async def test_send_meme_to_user_retries_assigned_undelivered_nudge(monkeypatch):
    calls: list[str] = []

    async def first_meme_nudge_variant(_user_id: int, *, is_first_meme: bool) -> str:
        assert is_first_meme is False
        calls.append("pending_nudge")
        return "treatment"

    async def create_reaction(*_args):
        calls.append("create_reaction")

    async def send_nudge(*_args):
        calls.append("send_nudge")

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
    monkeypatch.setattr(
        meme_sender,
        "get_first_meme_nudge_variant_to_send",
        first_meme_nudge_variant,
    )
    monkeypatch.setattr(meme_sender, "create_user_meme_reaction", create_reaction)
    monkeypatch.setattr(meme_sender, "maybe_send_first_meme_nudge", send_nudge)

    await meme_sender.send_meme_to_user(bot=object(), user_id=12001, meme=_meme())

    assert calls == ["pending_nudge", "create_reaction", "send_nudge"]


@pytest.mark.asyncio
async def test_send_meme_to_user_does_not_assign_new_nudge_for_returning_user(monkeypatch):
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
    first_meme_nudge_variant = AsyncMock()
    monkeypatch.setattr(
        meme_sender,
        "get_first_meme_nudge_variant_to_send",
        first_meme_nudge_variant,
    )
    monkeypatch.setattr(meme_sender, "create_user_meme_reaction", AsyncMock())

    await meme_sender.send_meme_to_user(bot=object(), user_id=12001, meme=_meme())

    first_meme_nudge_variant.assert_awaited_once_with(12001, is_first_meme=False)
