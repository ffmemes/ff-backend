"""Tests for admin meme inspect HTTP API."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.admin.auth import require_admin_token
from src.admin.router import router as admin_router
from src.admin.service import (
    MAX_INLINE_MEDIA_BYTES,
    _compact_ocr,
    build_meme_inspect_payload,
    media_content_type,
    media_filename,
)


def _app_with_admin() -> FastAPI:
    app = FastAPI()
    app.include_router(admin_router)
    return app


@pytest.fixture
def admin_token(monkeypatch):
    token = "test-admin-token-not-real"
    monkeypatch.setattr("src.admin.auth.settings.ADMIN_API_TOKEN", token)
    return token


@pytest.mark.asyncio
async def test_require_admin_token_missing_config(monkeypatch):
    monkeypatch.setattr("src.admin.auth.settings.ADMIN_API_TOKEN", None)
    with pytest.raises(Exception) as exc_info:
        await require_admin_token(authorization=None, x_admin_token=None)
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_require_admin_token_rejects_bad_token(admin_token):
    with pytest.raises(Exception) as exc_info:
        await require_admin_token(authorization="Bearer wrong", x_admin_token=None)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_require_admin_token_accepts_bearer_and_header(admin_token):
    await require_admin_token(authorization=f"Bearer {admin_token}", x_admin_token=None)
    await require_admin_token(authorization=None, x_admin_token=admin_token)


def test_compact_ocr_empty():
    assert _compact_ocr(None)["has_ocr"] is False
    assert _compact_ocr({})["has_ocr"] is False


def test_compact_ocr_from_raw_result():
    ocr = {
        "calculated_at": "2026-08-13T00:00:00+00:00",
        "model": "google/gemma-4-31b-it:free",
        "raw_result": {
            "ocr_text": "hello",
            "description": "a cat meme",
            "language": "en",
        },
    }
    compact = _compact_ocr(ocr)
    assert compact["has_ocr"] is True
    assert compact["text"] == "hello"
    assert compact["description"] == "a cat meme"
    assert compact["language"] == "en"
    assert compact["model"] == "google/gemma-4-31b-it:free"


def test_media_helpers():
    assert media_content_type("video") == "video/mp4"
    assert media_content_type("animation") == "image/gif"
    assert media_content_type("image") == "image/jpeg"
    assert media_filename(42, "video") == "meme_42.mp4"
    assert media_filename(42, "image") == "meme_42.jpg"


@pytest.mark.asyncio
async def test_build_meme_inspect_payload_not_found():
    with patch("src.admin.service.get_meme_by_id", new=AsyncMock(return_value=None)):
        assert await build_meme_inspect_payload(999) is None


@pytest.mark.asyncio
async def test_build_meme_inspect_payload_compact():
    meme = {
        "id": 101,
        "status": "ok",
        "type": "image",
        "language_code": "ru",
        "caption": "cap",
        "published_at": datetime(2024, 6, 1, 12, 0, 0),
        "created_at": datetime(2024, 6, 1, 12, 0, 0),
        "updated_at": None,
        "duplicate_of": None,
        "meme_source_id": 7,
        "raw_meme_id": 55,
        "telegram_file_id": "file_abc",
        "ocr_result": {
            "description": "joke about code",
            "text": "print hello",
            "language": "en",
            "calculated_at": "2026-08-01T12:00:00+00:00",
            "model": "google/gemma-4-31b-it:free",
        },
    }
    source = {
        "id": 7,
        "type": "telegram",
        "url": "https://t.me/example",
        "status": "parsing_enabled",
        "language_code": "ru",
        "parsed_at": None,
    }
    stats = {
        "nlikes": 10,
        "ndislikes": 2,
        "nmemes_sent": 20,
        "lr_smoothed": 0.7,
        "engagement_score": 1.2,
        "age_days": 5,
        "raw_impr_rank": 1,
        "sec_to_react": 3.5,
        "invited_count": 0,
        "updated_at": datetime(2024, 6, 2, 12, 0, 0),
    }

    with (
        patch("src.admin.service.get_meme_by_id", new=AsyncMock(return_value=meme)),
        patch("src.admin.service.get_meme_source_by_id", new=AsyncMock(return_value=source)),
        patch("src.admin.service.get_meme_stats", new=AsyncMock(return_value=stats)),
    ):
        payload = await build_meme_inspect_payload(101)

    assert payload is not None
    assert payload["meme"]["id"] == 101
    assert payload["meme"]["has_telegram_file_id"] is True
    assert payload["source"]["url"] == "https://t.me/example"
    assert payload["stats"]["nlikes"] == 10
    assert payload["ocr"]["description"] == "joke about code"
    assert payload["media"]["download_path"] == "/admin/memes/101/media"
    assert "telegram_file_id" not in payload["meme"]


@pytest.mark.asyncio
async def test_inspect_endpoint_auth_and_payload(admin_token):
    payload = {
        "meme": {"id": 5, "has_telegram_file_id": True},
        "source": None,
        "stats": None,
        "ocr": {"has_ocr": False},
        "media": {
            "available": True,
            "download_path": "/admin/memes/5/media",
            "content_type": "image/jpeg",
            "filename": "meme_5.jpg",
        },
    }
    app = _app_with_admin()
    with patch(
        "src.admin.router.build_meme_inspect_payload",
        new=AsyncMock(return_value=payload),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            unauth = await client.get("/admin/memes/5")
            assert unauth.status_code == 401

            ok = await client.get(
                "/admin/memes/5",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert ok.status_code == 200
            assert ok.json()["meme"]["id"] == 5


@pytest.mark.asyncio
async def test_inspect_endpoint_not_found(admin_token):
    app = _app_with_admin()
    with patch(
        "src.admin.router.build_meme_inspect_payload",
        new=AsyncMock(return_value=None),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/admin/memes/404",
                headers={"X-Admin-Token": admin_token},
            )
            assert resp.status_code == 404


@pytest.mark.asyncio
async def test_media_endpoint_downloads(admin_token):
    meme = {
        "id": 9,
        "type": "image",
        "telegram_file_id": "tg_file",
    }
    app = _app_with_admin()
    with (
        patch("src.admin.router.get_meme_by_id", new=AsyncMock(return_value=meme)),
        patch(
            "src.admin.router.download_meme_content_from_tg",
            new=AsyncMock(return_value=b"\xff\xd8fakejpeg"),
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/admin/memes/9/media",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert resp.status_code == 200
            assert resp.content == b"\xff\xd8fakejpeg"
            assert resp.headers["content-type"].startswith("image/jpeg")
            assert "meme_9.jpg" in resp.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_media_endpoint_missing_file_id(admin_token):
    meme = {"id": 9, "type": "image", "telegram_file_id": None}
    app = _app_with_admin()
    with patch("src.admin.router.get_meme_by_id", new=AsyncMock(return_value=meme)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/admin/memes/9/media",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert resp.status_code == 404


@pytest.mark.asyncio
async def test_include_media_inline_base64(admin_token):
    payload = {
        "meme": {"id": 3},
        "source": None,
        "stats": None,
        "ocr": {"has_ocr": False},
        "media": {
            "available": True,
            "download_path": "/admin/memes/3/media",
            "content_type": "image/jpeg",
            "filename": "meme_3.jpg",
        },
    }
    meme = {"id": 3, "telegram_file_id": "f", "type": "image"}
    app = _app_with_admin()
    with (
        patch(
            "src.admin.router.build_meme_inspect_payload",
            new=AsyncMock(return_value=payload),
        ),
        patch("src.admin.router.get_meme_by_id", new=AsyncMock(return_value=meme)),
        patch(
            "src.admin.router.download_meme_content_from_tg",
            new=AsyncMock(return_value=b"abc"),
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/admin/memes/3",
                params={"include_media": "true"},
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["media"]["base64"] == "YWJj"
            assert body["media"]["size_bytes"] == 3


@pytest.mark.asyncio
async def test_include_media_too_large(admin_token):
    payload = {
        "meme": {"id": 3},
        "source": None,
        "stats": None,
        "ocr": {"has_ocr": False},
        "media": {
            "available": True,
            "download_path": "/admin/memes/3/media",
            "content_type": "video/mp4",
            "filename": "meme_3.mp4",
        },
    }
    meme = {"id": 3, "telegram_file_id": "f", "type": "video"}
    huge = b"x" * (MAX_INLINE_MEDIA_BYTES + 1)
    app = _app_with_admin()
    with (
        patch(
            "src.admin.router.build_meme_inspect_payload",
            new=AsyncMock(return_value=payload),
        ),
        patch("src.admin.router.get_meme_by_id", new=AsyncMock(return_value=meme)),
        patch(
            "src.admin.router.download_meme_content_from_tg",
            new=AsyncMock(return_value=huge),
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/admin/memes/3",
                params={"include_media": "true"},
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert "base64" not in body["media"] or body["media"].get("base64") is None
            assert "too large" in body["media"]["inline_error"]
