from unittest.mock import AsyncMock

from sqlalchemy import delete, select
from telegram.error import BadRequest
from tests.factories import FIXED_DT, create_user

from src.database import engine, fetch_one, meme_source, user
from src.tgbot.handlers.upload.service import create_meme_from_meme_raw_upload
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


async def test_uploads_reuse_the_uploaders_source():
    user_id = 910_000_000_013
    async with engine.begin() as conn:
        await create_user(conn, user_id)

    upload = {
        "user_id": user_id,
        "forward_origin": None,
        "date": FIXED_DT,
        "media": {"file_id": "uploaded-photo"},
        "language_code": "ru",
    }
    try:
        first = await create_meme_from_meme_raw_upload({**upload, "id": 1})
        second = await create_meme_from_meme_raw_upload({**upload, "id": 2})

        source = await fetch_one(
            select(meme_source).where(meme_source.c.id == first["meme_source_id"])
        )
        assert first["meme_source_id"] == second["meme_source_id"]
        assert source["url"] == f"tg://user?id={user_id}"
        assert source["type"] == "user upload"
        assert source["status"] == "created"
        assert source["added_by"] == user_id
    finally:
        async with engine.begin() as conn:
            await conn.execute(delete(meme_source).where(meme_source.c.added_by == user_id))
            await conn.execute(delete(user).where(user.c.id == user_id))
