"""Unit tests for the shared Paperclip HTTP client.

Self-contained: no DB, no live network. The client takes an injectable
`opener` so we can mimic urlopen responses, HTTPError 4xx/5xx, URLError
transport failures, and JSONDecodeError without monkeypatching urllib
globally.
"""

from __future__ import annotations

import io
import json
import sys
import urllib.error
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from paperclip_http import (  # noqa: E402
    PaperclipAPIError,
    PaperclipClient,
    paperclip_base_url,
    parse_ts,
    redact,
    require_credentials,
)


class _FakeResp:
    """Minimal context-manager that mimics what urlopen returns."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def _opener_returning(payload: object, *, captured: list[dict]):
    """Build a urlopen replacement that records every call and returns JSON.

    Tests use `captured` to assert on URL / headers / body / timeout — the
    exact surface that previously diverged across the three caller scripts.
    """

    def opener(req, *, data=None, timeout=None):
        captured.append(
            {
                "url": req.full_url,
                "method": req.get_method(),
                "headers": dict(req.header_items()),
                "data": data,
                "timeout": timeout,
            }
        )
        return _FakeResp(json.dumps(payload).encode())

    return opener


def _opener_raising(exc: BaseException):
    def opener(req, *, data=None, timeout=None):
        raise exc

    return opener


def test_request_sends_bearer_and_user_agent():
    captured: list[dict] = []
    client = PaperclipClient(
        "https://example.test/",
        "secret-key-123",
        user_agent="test-ua/1.0",
        opener=_opener_returning({"ok": True}, captured=captured),
    )
    result = client.get("/api/things", {"a": "1", "b": "two"})
    assert result == {"ok": True}
    assert len(captured) == 1
    call = captured[0]
    # Trailing / on base_url is normalized; query string composes; no double //.
    assert call["url"] == "https://example.test/api/things?a=1&b=two"
    assert call["method"] == "GET"
    # Bearer header carries the raw key — required for the API to authenticate.
    # The redaction layer only protects logs, not outgoing requests.
    assert call["headers"]["Authorization"] == "Bearer secret-key-123"
    assert call["headers"]["User-agent"] == "test-ua/1.0"
    assert call["timeout"] == 30


def test_post_sets_content_type_and_serializes_body():
    captured: list[dict] = []
    client = PaperclipClient(
        "https://example.test",
        "k",
        opener=_opener_returning({"id": "x"}, captured=captured),
    )
    client.post("/api/agents/abc/skills/sync", {"desiredSkills": ["a", "b"]})
    call = captured[0]
    assert call["method"] == "POST"
    assert call["headers"]["Content-type"] == "application/json"
    assert call["data"] == b'{"desiredSkills": ["a", "b"]}'


def test_request_redacts_bearer_and_url_credentials_in_error_body():
    body = (
        b"unauthorized; tried Bearer abcdef0123456789ABCDEF0123456789xyz "
        b"against https://user:hunter2@db.example.test/path"
    )
    err = urllib.error.HTTPError("https://example.test/api/x", 401, "Auth", {}, io.BytesIO(body))
    client = PaperclipClient("https://example.test", "k", opener=_opener_raising(err))
    with pytest.raises(PaperclipAPIError) as info:
        client.get("/api/x")
    msg = str(info.value)
    assert info.value.code == 401
    assert info.value.kind == "http"
    # The bearer literal must be redacted; the user:pass URL must be redacted.
    assert "abcdef0123456789ABCDEF0123456789xyz" not in msg
    assert "[REDACTED]" in msg
    assert "hunter2" not in msg
    # Legacy callers branch on this exact prefix; preserve it.
    assert msg.startswith("HTTP 401 for /api/x:")


def test_redact_handles_token_keyword_assignment_form():
    out = redact("token=hunter2 something secret = topsecret api_key:abc")
    assert "hunter2" not in out
    assert "topsecret" not in out
    assert "abc" not in out
    assert out.count("[REDACTED]") >= 3


def test_redact_truncates_with_ellipsis():
    out = redact("x" * 1000, limit=20)
    assert len(out) == 20
    assert out.endswith("…")


def test_request_translates_url_error_to_transport_kind():
    err = urllib.error.URLError("connection refused")
    client = PaperclipClient("https://example.test", "k", opener=_opener_raising(err))
    with pytest.raises(PaperclipAPIError) as info:
        client.get("/api/y")
    assert info.value.kind == "transport"
    assert info.value.code is None
    assert "connection refused" in str(info.value)
    assert str(info.value).startswith("transport/decode failure for /api/y:")


def test_request_translates_decode_failure_to_transport_kind():
    @contextmanager
    def bad_body():
        yield _FakeResp(b"not-json{{{")

    def opener(req, *, data=None, timeout=None):
        return _FakeResp(b"not-json{{{")

    client = PaperclipClient("https://example.test", "k", opener=opener)
    with pytest.raises(PaperclipAPIError) as info:
        client.get("/api/z")
    assert info.value.kind == "transport"


def test_paperclip_base_url_strips_trailing_api():
    assert paperclip_base_url({"PAPERCLIP_URL": "https://x.example/api/"}) == "https://x.example"
    assert paperclip_base_url({"PAPERCLIP_URL": "https://x.example/api"}) == "https://x.example"
    assert paperclip_base_url({"PAPERCLIP_URL": "https://x.example/"}) == "https://x.example"
    # PAPERCLIP_API_URL takes precedence when both are set (matches runtime).
    assert (
        paperclip_base_url(
            {"PAPERCLIP_API_URL": "https://api.example/", "PAPERCLIP_URL": "https://other"}
        )
        == "https://api.example"
    )
    assert paperclip_base_url({}) is None


def test_require_credentials():
    assert require_credentials({}) is None
    assert require_credentials({"PAPERCLIP_URL": "https://x.example"}) is None
    assert require_credentials(
        {"PAPERCLIP_URL": "https://x.example", "PAPERCLIP_API_KEY": "k"}
    ) == ("https://x.example", "k")


def test_parse_ts_returns_aware_datetime_or_none():
    dt = parse_ts("2026-05-09T12:00:00Z")
    assert dt is not None
    assert dt.tzinfo is not None
    # Garbage timestamps must not raise — that used to crash whole audits.
    assert parse_ts("not-a-date") is None
    assert parse_ts(None) is None


def _paginate_opener(pages: list[object], captured: list[dict]):
    """Return an opener that serves `pages` in order, one per call."""
    iterator = iter(pages)

    def opener(req, *, data=None, timeout=None):
        captured.append(
            {
                "url": req.full_url,
                "method": req.get_method(),
            }
        )
        try:
            payload = next(iterator)
        except StopIteration:
            payload = []  # safety: empty list = end-of-data
        return _FakeResp(json.dumps(payload).encode())

    return opener


def test_paginate_collects_pages_and_dedupes():
    captured: list[dict] = []
    # Pages: two of size 200, then one of 1, then empty (probe).
    pages = [
        [{"id": f"i-{n}"} for n in range(200)],
        [{"id": f"i-{n}"} for n in range(200, 400)],
        [{"id": "i-400"}],
        [],  # probe
    ]
    client = PaperclipClient("https://x.example", "k", opener=_paginate_opener(pages, captured))
    items, trunc = client.paginate("/api/issues", limit=500)
    assert len(items) == 401
    # Distinct ids preserved.
    assert len({item["id"] for item in items}) == 401
    assert trunc["truncated"] is False


def test_paginate_flags_duplicate_page_offset_ignored():
    captured: list[dict] = []
    # Server hands back the same first page twice — classic "offset ignored".
    page = [{"id": f"i-{n}"} for n in range(5)]
    client = PaperclipClient(
        "https://x.example",
        "k",
        opener=_paginate_opener([page, page, page], captured),
    )
    items, trunc = client.paginate("/api/issues", limit=100, page_size=5)
    assert len(items) == 5
    assert trunc == {
        "truncated": True,
        "reason": "duplicate_page_offset_ignored",
        "atOffset": 5,
    }


def test_paginate_flags_unexpected_response_shape():
    def opener(req, *, data=None, timeout=None):
        return _FakeResp(json.dumps({"not": "a list"}).encode())

    client = PaperclipClient("https://x.example", "k", opener=opener)
    items, trunc = client.paginate("/api/issues", limit=10)
    assert items == []
    assert trunc["truncated"] is True
    assert trunc["reason"] == "unexpected_response_shape"
    assert trunc["atOffset"] == 0


def test_paginate_hit_limit_ceiling_when_probe_nonempty():
    captured: list[dict] = []
    # Exactly fills the requested limit, then probe finds another row.
    pages = [
        [{"id": f"i-{n}"} for n in range(5)],
        [{"id": "i-extra"}],  # probe sees more
    ]
    client = PaperclipClient(
        "https://x.example",
        "k",
        opener=_paginate_opener(pages, captured),
    )
    items, trunc = client.paginate("/api/issues", limit=5, page_size=5)
    assert len(items) == 5
    assert trunc["truncated"] is True
    assert trunc["reason"] == "hit_limit_ceiling"
    assert trunc["atOffset"] == 5


def test_paginate_exact_fit_is_not_truncated():
    captured: list[dict] = []
    pages = [
        [{"id": f"i-{n}"} for n in range(5)],
        [],  # probe is empty → exactly `limit` rows existed
    ]
    client = PaperclipClient(
        "https://x.example",
        "k",
        opener=_paginate_opener(pages, captured),
    )
    items, trunc = client.paginate("/api/issues", limit=5, page_size=5)
    assert len(items) == 5
    assert trunc["truncated"] is False


def test_paginate_page_failure_degrades_instead_of_raising():
    state = {"calls": 0}

    def opener(req, *, data=None, timeout=None):
        state["calls"] += 1
        if state["calls"] == 1:
            return _FakeResp(json.dumps([{"id": f"i-{n}"} for n in range(5)]).encode())
        # Second page fails with HTTP 503.
        raise urllib.error.HTTPError(req.full_url, 503, "down", {}, io.BytesIO(b"oops"))

    client = PaperclipClient("https://x.example", "k", opener=opener)
    items, trunc = client.paginate("/api/issues", limit=100, page_size=5)
    # First page collected; second page failure surfaces as truncation.
    assert len(items) == 5
    assert trunc["truncated"] is True
    assert trunc["reason"] == "page_request_failed"


def test_paperclip_api_error_string_format_for_legacy_callers():
    err_http = PaperclipAPIError(method="GET", path="/api/x", body="nope", code=404)
    assert str(err_http) == "HTTP 404 for /api/x: nope"
    err_transport = PaperclipAPIError(method="GET", path="/api/x", body="boom", kind="transport")
    assert str(err_transport).startswith("transport/decode failure for /api/x:")
