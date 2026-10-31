import io
from unittest.mock import AsyncMock, Mock

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import select

from src.database import engine, meme
from src.storage import upload
from src.storage.constants import MemeStatus, MemeType
from src.storage.deduplication.image_hash import dhash
from tests.factories import cleanup_test_data, create_meme, create_meme_source


def _image(seed: int, scale: float = 1.0, fmt="PNG", quality=95) -> bytes:
    img = Image.new("RGB", (400, 300), "white")
    draw = ImageDraw.Draw(img)
    for i in range(12):
        x, y = (seed * 37 + i * 53) % 400, (seed * 91 + i * 29) % 300
        draw.ellipse((x, y, x + 80, y + 60), fill=((seed * 50 + i * 20) % 256, 40, 200 - i * 10))
    img = img.resize((int(400 * scale), int(300 * scale)))
    buf = io.BytesIO()
    img.save(buf, fmt, quality=quality)
    return buf.getvalue()


def _bits(a: int, b: int) -> int:
    return bin((a ^ b) & (2**64 - 1)).count("1")


def test_dhash_stable_under_reencode_and_resize_far_for_different_images():
    original = dhash(_image(1))
    assert -(2**63) <= original < 2**63
    assert _bits(original, dhash(_image(1, fmt="JPEG", quality=60))) <= 4
    assert _bits(original, dhash(_image(1, scale=0.5))) <= 4
    assert _bits(original, dhash(_image(2))) >= 16


@pytest.mark.asyncio
async def test_upload_stores_image_hash_and_logs_shadow_match_without_merging(monkeypatch, caplog):
    content = _image(3)
    async with engine.connect() as conn:
        await create_meme_source(conn, id=10001)
        await create_meme(conn, id=10001, meme_source_id=10001, telegram_file_id="older")
        await create_meme(conn, id=10002, meme_source_id=10001, status="created")
        same_hash = meme.update().where(meme.c.id == 10001).values(image_hash=dhash(content))
        await conn.execute(same_hash)
        await conn.commit()

    photo = Mock(file_id="newer")
    bot = Mock(send_photo=AsyncMock(return_value=Mock(photo=[photo])))
    monkeypatch.setattr(upload, "bot", bot)
    try:
        with caplog.at_level("INFO", logger="src.storage.deduplication.image_hash"):
            result = await upload._upload_meme_content_to_tg(10002, MemeType.IMAGE, content)

        assert result["image_hash"] == dhash(content)
        assert result["status"] == MemeStatus.CREATED
        assert result["duplicate_of"] is None
        record = next(r for r in caplog.records if r.getMessage() == "phash shadow match")
        assert (record.ff_meme_id, record.ff_candidate_id) == (10002, 10001)
        assert record.ff_ocr_linked is False

        async with engine.connect() as conn:
            older = (await conn.execute(select(meme).where(meme.c.id == 10001))).first()
        assert older.status == "ok"
    finally:
        async with engine.connect() as conn:
            await cleanup_test_data(conn)


@pytest.mark.asyncio
async def test_hash_failure_does_not_break_upload():
    video = Mock(thumbnail=None)
    assert await upload._image_hash(1, MemeType.VIDEO, b"", video) is None
    assert await upload._image_hash(1, MemeType.IMAGE, b"not-an-image", None) is None
