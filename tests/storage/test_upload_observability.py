from unittest.mock import AsyncMock, Mock

import pytest
from telegram.error import BadRequest

from src.storage import upload
from src.storage.constants import MemeStatus, MemeType


@pytest.mark.asyncio
async def test_upload_meme_content_bad_request_captures_sentry_context(monkeypatch):
    telegram_error = BadRequest("Photo_invalid_dimensions")
    store_upload = AsyncMock(side_effect=telegram_error)
    update_meme = AsyncMock()
    capture_failure = Mock()

    monkeypatch.setattr(upload, "_upload_meme_content_to_tg", store_upload)
    monkeypatch.setattr(upload, "update_meme", update_meme)
    monkeypatch.setattr(upload, "capture_telegram_storage_upload_failure", capture_failure)
    monkeypatch.setattr(upload.asyncio, "sleep", AsyncMock())

    meme = {"id": 101, "type": MemeType.IMAGE}
    context = {"user_upload": {"upload_id": 202, "user_id": 303}}

    result = await upload.upload_meme_content_to_tg(
        meme,
        b"image-bytes",
        observability_context=context,
    )

    assert result is None
    store_upload.assert_awaited_once_with(
        meme_id=101,
        meme_type=MemeType.IMAGE,
        content=b"image-bytes",
    )
    update_meme.assert_awaited_once_with(101, status=MemeStatus.BROKEN_CONTENT_LINK)
    capture_failure.assert_called_once_with(
        meme,
        reason="bad_request",
        attempt=1,
        max_attempts=3,
        content_size=len(b"image-bytes"),
        error=telegram_error,
        observability_context=context,
    )
