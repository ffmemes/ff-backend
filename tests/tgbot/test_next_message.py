from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.error import NetworkError

from src.storage.constants import MemeType
from src.storage.schemas import MemeData
from src.tgbot.senders import next_message


def _meme() -> MemeData:
    return MemeData(
        id=123,
        type=MemeType.IMAGE,
        telegram_file_id="photo-file-id",
        caption="<b>caption</b>",
    )


@pytest.mark.asyncio
async def test_next_message_does_not_try_another_meme_after_ambiguous_send_error(
    monkeypatch,
):
    get_next = AsyncMock(return_value=_meme())
    send_new = AsyncMock(side_effect=NetworkError("Server disconnected"))
    create_reaction = AsyncMock()
    check_queue = AsyncMock()

    monkeypatch.setattr(
        next_message,
        "get_user_info",
        AsyncMock(return_value={"interface_lang": "en", "nmemes_sent": 1}),
    )
    monkeypatch.setattr(next_message, "collect_user_languages", AsyncMock(return_value={"en"}))
    monkeypatch.setattr(next_message, "get_popup_to_send", AsyncMock(return_value=None))
    monkeypatch.setattr(next_message, "get_next_meme_for_user", get_next)
    monkeypatch.setattr(next_message, "get_visible_meme_like_count", AsyncMock(return_value=0))
    monkeypatch.setattr(next_message, "meme_reaction_keyboard", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        next_message,
        "get_meme_caption_for_user_id",
        AsyncMock(return_value="<b>caption</b>"),
    )
    monkeypatch.setattr(next_message, "send_new_message_with_meme", send_new)
    monkeypatch.setattr(next_message, "create_user_meme_reaction", create_reaction)
    monkeypatch.setattr(next_message.meme_queue, "check_queue", check_queue)

    with pytest.raises(NetworkError):
        await next_message.next_message(
            bot=object(),
            user_id=12001,
            prev_update=SimpleNamespace(callback_query=None),
        )

    assert get_next.await_count == 1
    assert send_new.await_count == 1
    create_reaction.assert_not_awaited()
    check_queue.assert_not_awaited()


@pytest.mark.asyncio
async def test_replace_previous_message_does_not_send_new_message_after_transient_edit_error(
    monkeypatch,
):
    async def fail_edit(*_args, **_kwargs):
        raise NetworkError("Server disconnected without sending a response")

    send_new = AsyncMock()
    monkeypatch.setattr(next_message, "edit_last_message_with_meme", fail_edit)
    monkeypatch.setattr(next_message, "send_new_message_with_meme", send_new)

    with pytest.raises(NetworkError):
        await next_message._replace_previous_message(
            bot=object(),
            previous_message=SimpleNamespace(chat_id=12001),
            meme=_meme(),
            reply_markup=None,
        )

    send_new.assert_not_awaited()
