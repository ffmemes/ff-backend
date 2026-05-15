from io import BytesIO

import pytest

from src.flows.storage import memes
from src.storage.constants import MemeType


@pytest.mark.asyncio
async def test_add_watermark_to_meme_content_returns_bytes_for_images(monkeypatch):
    watermarked_content = BytesIO(b"watermarked-image")
    watermarked_content.name = "image.jpeg"

    monkeypatch.setattr(memes, "add_watermark", lambda content: watermarked_content)

    result = await memes.add_watermark_to_meme_content(b"raw-image", MemeType.IMAGE)

    assert result == b"watermarked-image"
    assert isinstance(result, bytes)
