from io import BytesIO

from src.storage import watermark
from src.storage.constants import MemeType


def test_add_watermark_to_meme_content_returns_bytes_for_images(monkeypatch):
    watermarked_content = BytesIO(b"watermarked-image")
    watermarked_content.name = "image.jpeg"

    monkeypatch.setattr(watermark, "add_watermark", lambda content: watermarked_content)

    result = watermark.add_watermark_to_meme_content(b"raw-image", MemeType.IMAGE)

    assert result == b"watermarked-image"
    assert isinstance(result, bytes)
