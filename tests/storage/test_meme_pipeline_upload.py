import logging
from io import BytesIO
from unittest.mock import AsyncMock, call

import pytest
from PIL import Image

from src.flows.storage import memes
from src.storage import watermark
from src.storage.constants import MemeType


def test_watermark_returns_jpeg_bytes():
    original = BytesIO()
    Image.new("RGB", (320, 240), "white").save(original, "PNG")

    result = watermark.add_watermark_to_meme_content(original.getvalue(), MemeType.IMAGE)

    with Image.open(BytesIO(result)) as image:
        assert image.format == "JPEG"
        assert image.size == (320, 240)
        assert image.getextrema() != ((255, 255),) * 3


def test_watermark_rejects_invalid_image():
    assert watermark.add_watermark_to_meme_content(b"invalid", MemeType.IMAGE) is None


@pytest.mark.parametrize("meme_type", [MemeType.VIDEO, MemeType.ANIMATION])
def test_watermark_preserves_non_images(meme_type):
    content = b"unchanged-media"
    assert watermark.add_watermark_to_meme_content(content, meme_type) is content


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
