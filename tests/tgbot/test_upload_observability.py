from unittest.mock import AsyncMock, patch

import pytest
from telegram.error import BadRequest

from src.storage.constants import MemeStatus, MemeType
from src.tgbot.handlers.upload import moderation
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


@pytest.mark.asyncio
async def test_uploaded_meme_auto_review_handles_oversized_telegram_download():
    error = BadRequest("File is too big")
    meme = {"id": 12003, "type": MemeType.IMAGE, "telegram_file_id": "raw-file-id"}
    meme_upload = {
        "id": 12002,
        "user_id": 12001,
        "message_id": 12004,
        "media": {"file_size": 99_000_000},
    }

    with (
        patch.object(
            moderation,
            "download_meme_content_from_tg",
            new=AsyncMock(side_effect=error),
        ),
        patch.object(
            moderation,
            "get_user_info",
            new=AsyncMock(return_value={"interface_lang": "en"}),
        ),
        patch.object(moderation, "update_meme", new=AsyncMock()) as update_meme,
        patch.object(moderation, "_notify_uploader", new=AsyncMock()) as notify,
        patch.object(moderation, "capture_handled_issue") as capture_issue,
        patch.object(moderation, "capture_handled_exception") as capture_exception,
    ):
        await uploaded_meme_auto_review(meme, meme_upload, AsyncMock())

    update_meme.assert_awaited_once_with(12003, status=MemeStatus.BROKEN_CONTENT_LINK)
    notify.assert_awaited_once()
    assert "too big" in notify.await_args.args[2]
    capture_issue.assert_called_once()
    assert capture_issue.call_args.kwargs["tags"]["ff.failure_kind"] == "telegram_file_too_big"
    capture_exception.assert_not_called()
