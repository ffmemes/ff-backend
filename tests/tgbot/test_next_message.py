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
