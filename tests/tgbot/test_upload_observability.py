from unittest.mock import AsyncMock, patch

import pytest

from src.storage.constants import MemeType
from src.tgbot.handlers.upload.moderation import uploaded_meme_auto_review


@pytest.mark.asyncio
async def test_uploaded_meme_auto_review_captures_unhandled_failure():
    error = RuntimeError("boom")
    meme = {"id": 12003, "type": MemeType.IMAGE, "telegram_file_id": "raw-file-id"}
    meme_upload = {"id": 12002, "user_id": 12001, "message_id": 12004}

    with (
        patch(
            "src.tgbot.handlers.upload.moderation._uploaded_meme_auto_review",
            new=AsyncMock(side_effect=error),
        ),
        patch("src.tgbot.handlers.upload.moderation.capture_handled_exception") as capture,
        pytest.raises(RuntimeError, match="boom"),
    ):
        await uploaded_meme_auto_review(meme, meme_upload, AsyncMock())

    capture.assert_called_once()
    args, kwargs = capture.call_args
    assert args == ("user_upload.auto_review_unhandled", error)
    assert kwargs["user_id"] == 12001
    assert kwargs["tags"]["ff.module"] == "user_upload"
    assert kwargs["contexts"]["meme"]["id"] == 12003
