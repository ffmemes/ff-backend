"""Tests for src/flows/storage/describe_memes.py

Unit tests for parsing logic (no external deps).
Integration tests for the query and describe pipeline (need DB + mocked HTTP).
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from src.database import engine, meme, meme_source, meme_stats
from src.flows.storage.describe_memes import (
    ALL_FAILED,
    QUOTA_EXHAUSTED,
    RATE_LIMITED,
    _parse_vision_response,
    call_openrouter_vision,
    describe_single_meme,
    get_memes_to_describe,
)
from tests.factories import (
    TEST_ID_START,
    cleanup_test_data,
    create_meme,
    create_meme_source,
    create_meme_stats,
)

# ─── Unit tests: _parse_vision_response ───


class TestParseVisionResponse:
    """Pure unit tests — no DB, no network."""

    def test_clean_json(self):
        raw = '{"ocr_text": "hello world", "description": "A meme", "language": "en"}'
        result = _parse_vision_response(raw)
        assert result["ocr_text"] == "hello world"
        assert result["description"] == "A meme"
        assert result["language"] == "en"

    def test_json_with_markdown_fences(self):
        raw = '```json\n{"ocr_text": "test", "description": "desc", "language": "ru"}\n```'
        result = _parse_vision_response(raw)
        assert result["ocr_text"] == "test"
        assert result["language"] == "ru"

    def test_json_with_bare_fences(self):
        raw = '```\n{"ocr_text": "test", "description": "desc", "language": "en"}\n```'
        result = _parse_vision_response(raw)
        assert result["ocr_text"] == "test"

    def test_invalid_escape_sequences(self):
        """Models sometimes produce \\' or \\k which aren't valid JSON escapes."""
        raw = r'{"ocr_text": "it\'s a test", "description": "desc", "language": "en"}'
        result = _parse_vision_response(raw)
        assert "test" in result["ocr_text"]

    def test_regex_extraction_fallback(self):
        """Severely malformed JSON falls back to regex field extraction."""
        raw = (
            '{"ocr_text": "hello", "description": "a meme about cats",'
            ' "language": "en", extra_garbage'
        )
        result = _parse_vision_response(raw)
        assert result["description"] == "a meme about cats"

    def test_multiline_ocr_text(self):
        raw = '{"ocr_text": "line1\\nline2\\nline3", "description": "text meme", "language": "ru"}'
        result = _parse_vision_response(raw)
        assert "line1" in result["ocr_text"]
        assert "line3" in result["ocr_text"]

    def test_empty_ocr_text(self):
        raw = '{"ocr_text": "", "description": "image only meme", "language": "en"}'
        result = _parse_vision_response(raw)
        assert result["ocr_text"] == ""
        assert result["description"] == "image only meme"

    def test_unicode_content(self):
        raw = '{"ocr_text": "Привет мир 🤣", "description": "Russian meme", "language": "ru"}'
        result = _parse_vision_response(raw)
        assert "Привет" in result["ocr_text"]

    def test_completely_unparseable_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_vision_response("this is not json at all")

    def test_whitespace_and_leading_json_label(self):
        raw = '  json\n{"ocr_text": "x", "description": "y", "language": "en"}  '
        result = _parse_vision_response(raw)
        assert result["ocr_text"] == "x"

    def test_missing_description_but_has_ocr(self):
        """Partial response — only ocr_text present."""
        raw = '{"ocr_text": "some text"}'
        result = _parse_vision_response(raw)
        assert result["ocr_text"] == "some text"
        assert "description" not in result

    def test_nested_quotes_in_ocr_text(self):
        raw = '{"ocr_text": "He said \\"hello\\"", "description": "quote meme", "language": "en"}'
        result = _parse_vision_response(raw)
        assert "hello" in result["ocr_text"]


# ─── Unit tests: call_openrouter_vision ───


def _mock_request():
    """Dummy request for httpx.Response construction."""
    return httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")


def _ok_response(content_json: str) -> httpx.Response:
    """Build a 200 response with vision model output."""
    body = json.dumps({"choices": [{"message": {"content": content_json}}]})
    return httpx.Response(200, text=body, request=_mock_request())


def _error_response(status: int, body: str = "") -> httpx.Response:
    return httpx.Response(status, text=body, request=_mock_request())


def _mock_httpx_client(client_instance):
    """Patch httpx.AsyncClient so `async with ... as client` returns client_instance."""
    patcher = patch("src.flows.storage.describe_memes.httpx.AsyncClient")
    MockClient = patcher.start()
    MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
    MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
    return patcher


class TestCallOpenrouterVision:
    """Tests for the model fallback chain with mocked HTTP."""

    @pytest.fixture
    def mock_log(self):
        log = AsyncMock()
        log.debug = lambda *a, **k: None
        log.info = lambda *a, **k: None
        log.warning = lambda *a, **k: None
        return log

    @pytest.mark.asyncio
    async def test_first_model_succeeds(self, mock_log):
        client = AsyncMock()
        client.post.return_value = _ok_response(
            '{"ocr_text": "test", "description": "a meme", "language": "en"}'
        )
        patcher = _mock_httpx_client(client)
        try:
            result = await call_openrouter_vision("base64data", mock_log)
        finally:
            patcher.stop()

        assert result["description"] == "a meme"
        assert "__model" in result
        assert client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_429_returns_rate_limited_immediately(self, mock_log):
        """HTTP 429 returns RATE_LIMITED sentinel immediately — no per-model fallback.

        Rate limits on OpenRouter free tier are account-level (shared across models),
        so trying the next model would also 429. Caller is expected to back off.
        """
        client = AsyncMock()
        client.post.return_value = _error_response(429, "rate limited")
        patcher = _mock_httpx_client(client)
        try:
            result = await call_openrouter_vision("base64data", mock_log)
        finally:
            patcher.stop()

        assert result.get(RATE_LIMITED) is True
        assert client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_fallback_on_403(self, mock_log):
        """First model 403 (access denied), second succeeds."""
        client = AsyncMock()
        client.post.side_effect = [
            _error_response(403, "forbidden"),
            _ok_response('{"ocr_text": "", "description": "fallback", "language": "en"}'),
        ]
        patcher = _mock_httpx_client(client)
        try:
            result = await call_openrouter_vision("base64data", mock_log)
        finally:
            patcher.stop()

        assert result["description"] == "fallback"

    @pytest.mark.asyncio
    async def test_all_models_fail_mixed(self, mock_log):
        """Mix of 403, timeout, bad JSON -> ALL_FAILED sentinel."""
        client = AsyncMock()
        client.post.side_effect = [
            _error_response(403, "forbidden"),
            httpx.ReadTimeout("timeout"),
            _ok_response("not valid inner json"),
            _error_response(403),
            _error_response(403),
            _error_response(403),
        ]
        patcher = _mock_httpx_client(client)
        try:
            result = await call_openrouter_vision("base64data", mock_log)
        finally:
            patcher.stop()

        assert result.get(ALL_FAILED) is True

    @pytest.mark.asyncio
    async def test_timeout_triggers_fallback(self, mock_log):
        """httpx timeout on first model, second succeeds."""
        client = AsyncMock()
        client.post.side_effect = [
            httpx.ConnectTimeout("timeout"),
            _ok_response('{"ocr_text": "", "description": "after timeout", "language": "en"}'),
        ]
        patcher = _mock_httpx_client(client)
        try:
            result = await call_openrouter_vision("base64data", mock_log)
        finally:
            patcher.stop()

        assert result["description"] == "after timeout"

    @pytest.mark.asyncio
    async def test_model_returns_empty_content(self, mock_log):
        """Model returns valid JSON but empty content -> try next."""
        client = AsyncMock()
        client.post.side_effect = [
            _ok_response(""),  # empty content
            _ok_response('{"ocr_text": "x", "description": "good", "language": "en"}'),
        ]
        patcher = _mock_httpx_client(client)
        try:
            result = await call_openrouter_vision("base64data", mock_log)
        finally:
            patcher.stop()

        assert result["description"] == "good"

    @pytest.mark.asyncio
    async def test_402_returns_quota_exhausted_immediately(self, mock_log):
        """HTTP 402 (account balance exhausted) returns QUOTA_EXHAUSTED — no fallback.

        402 is account-level on OpenRouter — when the lifetime spend drops below $0
        all models (including free) return 402. Trying the next model would burn
        latency and still 402.
        """
        client = AsyncMock()
        client.post.return_value = _error_response(402, "Payment Required")
        patcher = _mock_httpx_client(client)
        try:
            result = await call_openrouter_vision("base64data", mock_log)
        finally:
            patcher.stop()

        assert result.get(QUOTA_EXHAUSTED) is True
        assert client.post.call_count == 1


# ─── Integration tests: get_memes_to_describe ───


class TestGetMemesToDescribe:
    """Integration tests — need running DB with migrations."""

    @pytest.fixture(autouse=True)
    async def setup_and_teardown(self):
        async with engine.begin() as conn:
            await cleanup_test_data(conn)

        yield

        async with engine.begin() as conn:
            await cleanup_test_data(conn)

    @pytest.mark.asyncio
    async def test_returns_memes_without_description(self):
        async with engine.begin() as conn:
            await create_meme_source(conn, TEST_ID_START)
            # Meme with no ocr_result
            await create_meme(conn, TEST_ID_START, TEST_ID_START)
            # Meme with description already set
            await conn.execute(
                meme.update().where(meme.c.id == TEST_ID_START).values(ocr_result=None)
            )
            await create_meme(conn, TEST_ID_START + 1, TEST_ID_START)
            await conn.execute(
                meme.update()
                .where(meme.c.id == TEST_ID_START + 1)
                .values(ocr_result={"description": "already described", "text": "some text"})
            )
            await conn.commit()

        results = await get_memes_to_describe(limit=10)
        meme_ids = [r["id"] for r in results]
        assert TEST_ID_START in meme_ids
        assert TEST_ID_START + 1 not in meme_ids

    @pytest.mark.asyncio
    async def test_skips_memes_with_3_failures(self):
        async with engine.begin() as conn:
            await create_meme_source(conn, TEST_ID_START)
            await create_meme(conn, TEST_ID_START, TEST_ID_START)
            await conn.execute(
                meme.update()
                .where(meme.c.id == TEST_ID_START)
                .values(ocr_result={"describe_failures": 3})
            )
            await conn.commit()

        results = await get_memes_to_describe(limit=10)
        meme_ids = [r["id"] for r in results]
        assert TEST_ID_START not in meme_ids

    @pytest.mark.asyncio
    async def test_includes_memes_with_fewer_than_3_failures(self):
        async with engine.begin() as conn:
            await create_meme_source(conn, TEST_ID_START)
            await create_meme(conn, TEST_ID_START, TEST_ID_START)
            await conn.execute(
                meme.update()
                .where(meme.c.id == TEST_ID_START)
                .values(ocr_result={"describe_failures": 2})
            )
            await conn.commit()

        results = await get_memes_to_describe(limit=10)
        meme_ids = [r["id"] for r in results]
        assert TEST_ID_START in meme_ids

    @pytest.mark.asyncio
    async def test_orders_by_likes_desc(self):
        async with engine.begin() as conn:
            await create_meme_source(conn, TEST_ID_START)
            await create_meme(conn, TEST_ID_START, TEST_ID_START)
            await create_meme(conn, TEST_ID_START + 1, TEST_ID_START)
            await create_meme_stats(conn, TEST_ID_START, nlikes=5)
            await create_meme_stats(conn, TEST_ID_START + 1, nlikes=50)
            # Clear ocr_result
            await conn.execute(
                meme.update()
                .where(meme.c.id.in_([TEST_ID_START, TEST_ID_START + 1]))
                .values(ocr_result=None)
            )
            await conn.commit()

        results = await get_memes_to_describe(limit=10)
        test_results = [r for r in results if r["id"] >= TEST_ID_START]
        assert len(test_results) == 2, f"Expected 2 test memes, got {len(test_results)}"
        assert test_results[0]["id"] == TEST_ID_START + 1  # 50 likes first
        assert test_results[1]["id"] == TEST_ID_START  # 5 likes second

    @pytest.mark.asyncio
    async def test_prioritizes_recent_uploads(self):
        """User uploads from last 24h should come before high-liked memes."""
        async with engine.begin() as conn:
            # Regular source
            await create_meme_source(conn, TEST_ID_START, type="telegram")
            # Upload source
            await create_meme_source(conn, TEST_ID_START + 1, type="user upload")

            # Popular meme from regular source
            await create_meme(conn, TEST_ID_START, TEST_ID_START)
            await create_meme_stats(conn, TEST_ID_START, nlikes=100)

            # Recent upload (less popular)
            now = datetime.now(timezone.utc)
            await create_meme(
                conn,
                TEST_ID_START + 1,
                TEST_ID_START + 1,
                created_at=now - timedelta(hours=1),
            )
            await create_meme_stats(conn, TEST_ID_START + 1, nlikes=1)

            # Clear ocr_result
            await conn.execute(
                meme.update()
                .where(meme.c.id.in_([TEST_ID_START, TEST_ID_START + 1]))
                .values(ocr_result=None)
            )
            await conn.commit()

        results = await get_memes_to_describe(limit=10)
        test_results = [r for r in results if r["id"] >= TEST_ID_START]
        assert len(test_results) == 2, f"Expected 2 test memes, got {len(test_results)}"
        # Recent upload should come first despite fewer likes
        assert test_results[0]["id"] == TEST_ID_START + 1

    @pytest.mark.asyncio
    async def test_skips_non_image_memes(self):
        async with engine.begin() as conn:
            await create_meme_source(conn, TEST_ID_START)
            await create_meme(conn, TEST_ID_START, TEST_ID_START, type="video")
            await conn.execute(
                meme.update().where(meme.c.id == TEST_ID_START).values(ocr_result=None)
            )
            await conn.commit()

        results = await get_memes_to_describe(limit=10)
        meme_ids = [r["id"] for r in results]
        assert TEST_ID_START not in meme_ids

    @pytest.mark.asyncio
    async def test_skips_non_ok_status(self):
        async with engine.begin() as conn:
            await create_meme_source(conn, TEST_ID_START)
            await create_meme(conn, TEST_ID_START, TEST_ID_START, status="created")
            await conn.execute(
                meme.update().where(meme.c.id == TEST_ID_START).values(ocr_result=None)
            )
            await conn.commit()

        results = await get_memes_to_describe(limit=10)
        meme_ids = [r["id"] for r in results]
        assert TEST_ID_START not in meme_ids

    @pytest.mark.asyncio
    async def test_respects_limit(self):
        async with engine.begin() as conn:
            await create_meme_source(conn, TEST_ID_START)
            for i in range(5):
                await create_meme(conn, TEST_ID_START + i, TEST_ID_START)
                await conn.execute(
                    meme.update().where(meme.c.id == TEST_ID_START + i).values(ocr_result=None)
                )
            await conn.commit()

        results = await get_memes_to_describe(limit=2)
        # Total results (including any pre-existing memes) respects limit
        assert len(results) <= 2


# ─── Integration tests: describe_single_meme ───


class TestDescribeSingleMeme:
    """Tests the full pipeline with mocked external calls."""

    @pytest.fixture(autouse=True)
    async def setup_and_teardown(self):
        async with engine.begin() as conn:
            await cleanup_test_data(conn)
            await create_meme_source(conn, TEST_ID_START)
            await create_meme(conn, TEST_ID_START, TEST_ID_START)
            await conn.execute(
                meme.update().where(meme.c.id == TEST_ID_START).values(ocr_result=None)
            )
            await conn.commit()
        yield
        async with engine.begin() as conn:
            await cleanup_test_data(conn)

    @pytest.fixture
    def mock_log(self):
        log = AsyncMock()
        log.debug = lambda *a, **k: None
        log.info = lambda *a, **k: None
        log.warning = lambda *a, **k: None
        return log

    @pytest.fixture
    def meme_row(self):
        return {
            "id": TEST_ID_START,
            "telegram_file_id": "test_file_id",
            "ocr_result": None,
            "language_code": "ru",
        }

    @pytest.mark.asyncio
    async def test_successful_describe(self, mock_log, meme_row):
        vision_result = {
            "ocr_text": "funny text",
            "description": "a cat meme",
            "language": "en",
            "__model": "google/gemma-3-27b-it:free",
        }

        with (
            patch(
                "src.flows.storage.describe_memes.download_meme_content_from_tg",
                new_callable=AsyncMock,
                return_value=b"fake_image_bytes",
            ),
            patch(
                "src.flows.storage.describe_memes.call_openrouter_vision",
                new_callable=AsyncMock,
                return_value=vision_result,
            ),
        ):
            status = await describe_single_meme(meme_row, mock_log)

        assert status == "ok"

        # Verify DB was updated with all required fields
        from src.database import fetch_one

        row = await fetch_one(meme.select().where(meme.c.id == TEST_ID_START))
        ocr = row["ocr_result"]
        assert ocr["description"] == "a cat meme"
        assert ocr["model"] == "google/gemma-3-27b-it:free"
        assert "calculated_at" in ocr
        # text field is critical — dedup and Wrapped read it directly
        assert ocr["text"] == "funny text"
        # raw_result preserves the original model output
        assert ocr["raw_result"]["ocr_text"] == "funny text"
        assert ocr["raw_result"]["description"] == "a cat meme"
        assert ocr["raw_result"]["language"] == "en"

    @pytest.mark.asyncio
    async def test_download_failure_increments_failures(self, mock_log, meme_row):
        with patch(
            "src.flows.storage.describe_memes.download_meme_content_from_tg",
            new_callable=AsyncMock,
            side_effect=Exception("Telegram timeout"),
        ):
            status = await describe_single_meme(meme_row, mock_log)

        assert status == "failed"

        from src.database import fetch_one

        row = await fetch_one(meme.select().where(meme.c.id == TEST_ID_START))
        assert row["ocr_result"]["describe_failures"] == 1

    @pytest.mark.asyncio
    async def test_rate_limited_returns_rate_limited(self, mock_log, meme_row):
        with (
            patch(
                "src.flows.storage.describe_memes.download_meme_content_from_tg",
                new_callable=AsyncMock,
                return_value=b"fake_image_bytes",
            ),
            patch(
                "src.flows.storage.describe_memes.call_openrouter_vision",
                new_callable=AsyncMock,
                return_value={RATE_LIMITED: True},
            ),
        ):
            status = await describe_single_meme(meme_row, mock_log)

        assert status == "rate_limited"

    @pytest.mark.asyncio
    async def test_all_failed_increments_failures(self, mock_log, meme_row):
        with (
            patch(
                "src.flows.storage.describe_memes.download_meme_content_from_tg",
                new_callable=AsyncMock,
                return_value=b"fake_image_bytes",
            ),
            patch(
                "src.flows.storage.describe_memes.call_openrouter_vision",
                new_callable=AsyncMock,
                return_value={ALL_FAILED: True},
            ),
        ):
            status = await describe_single_meme(meme_row, mock_log)

        assert status == "failed"

        from src.database import fetch_one

        row = await fetch_one(meme.select().where(meme.c.id == TEST_ID_START))
        assert row["ocr_result"]["describe_failures"] == 1

    @pytest.mark.asyncio
    async def test_known_language_updates_meme_language(self, mock_log, meme_row):
        vision_result = {
            "ocr_text": "Привет",
            "description": "Russian meme",
            "language": "ru",
            "__model": "google/gemma-3-27b-it:free",
        }

        with (
            patch(
                "src.flows.storage.describe_memes.download_meme_content_from_tg",
                new_callable=AsyncMock,
                return_value=b"fake_image_bytes",
            ),
            patch(
                "src.flows.storage.describe_memes.call_openrouter_vision",
                new_callable=AsyncMock,
                return_value=vision_result,
            ),
        ):
            status = await describe_single_meme(meme_row, mock_log)

        assert status == "ok"

        from src.database import fetch_one

        row = await fetch_one(meme.select().where(meme.c.id == TEST_ID_START))
        assert row["language_code"] == "ru"

    @pytest.mark.asyncio
    async def test_unknown_language_does_not_update(self, mock_log, meme_row):
        vision_result = {
            "ocr_text": "text",
            "description": "meme in klingon",
            "language": "tlh",  # not in KNOWN_LANGUAGES
            "__model": "google/gemma-3-27b-it:free",
        }

        with (
            patch(
                "src.flows.storage.describe_memes.download_meme_content_from_tg",
                new_callable=AsyncMock,
                return_value=b"fake_image_bytes",
            ),
            patch(
                "src.flows.storage.describe_memes.call_openrouter_vision",
                new_callable=AsyncMock,
                return_value=vision_result,
            ),
        ):
            status = await describe_single_meme(meme_row, mock_log)

        assert status == "ok"

        from src.database import fetch_one

        row = await fetch_one(meme.select().where(meme.c.id == TEST_ID_START))
        # Should keep original language, not update to "tlh"
        assert row["language_code"] == "ru"
