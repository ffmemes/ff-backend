from unittest.mock import AsyncMock

from telegram.error import BadRequest

from src.tgbot.handlers.upload.upload_meme import _edit_upload_callback_caption


async def test_edit_upload_callback_caption_ignores_not_modified():
    class Message:
        def __init__(self) -> None:
            self.edit_caption = AsyncMock(
                side_effect=BadRequest(
                    "Message is not modified: specified new message content and reply markup "
                    "are exactly the same"
                )
            )

    message = Message()

    await _edit_upload_callback_caption(message, "caption", reply_markup=None)

    message.edit_caption.assert_awaited_once()
