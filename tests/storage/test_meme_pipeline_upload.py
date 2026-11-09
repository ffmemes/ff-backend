import logging
from io import BytesIO
from unittest.mock import AsyncMock, call

from src.flows.storage import memes
from src.storage import watermark
from src.storage.constants import MemeType


def test_add_watermark_to_meme_content_returns_bytes_for_images(monkeypatch):
    watermarked_content = BytesIO(b"watermarked-image")
    watermarked_content.name = "image.jpeg"

    monkeypatch.setattr(watermark, "add_watermark", lambda content: watermarked_content)

    result = watermark.add_watermark_to_meme_content(b"raw-image", MemeType.IMAGE)

    assert result == b"watermarked-image"
    assert isinstance(result, bytes)


async def test_upload_batch_stops_after_five_consecutive_failures(monkeypatch, caplog):
    error = RuntimeError("Telegram unavailable")
    unloaded_memes = [{"id": meme_id} for meme_id in range(1, 12)]
    upload = AsyncMock(
        side_effect=[None, error, None, error, {"id": 5}, None, error, None, None, error]
    )
    monkeypatch.setattr(memes, "upload_meme_to_telegram", upload)
    monkeypatch.setattr(memes, "get_run_logger", lambda: logging.getLogger(__name__))

    await memes._process_unloaded_memes(unloaded_memes, "Telegram")

    assert upload.await_args_list == [call(meme) for meme in unloaded_memes[:10]]
    assert caplog.text.count("5 consecutive failures") == 1
