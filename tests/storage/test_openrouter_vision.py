import httpx
import pytest

from src.flows.storage import openrouter_vision


class _Log:
    def __init__(self):
        self.messages = []

    def error(self, message, *args):
        self.messages.append(("error", message % args if args else message))

    def info(self, message, *args):
        self.messages.append(("info", message % args if args else message))

    def warning(self, message, *args):
        self.messages.append(("warning", message % args if args else message))


class _FakeAsyncClient:
    def __init__(self, response=None, error=None, **_kwargs):
        self.response = response
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, *_args, **_kwargs):
        if self.error:
            raise self.error
        return self.response


def _response(status_code: int, payload: dict):
    request = httpx.Request("GET", "https://openrouter.ai/api/v1/key")
    return httpx.Response(status_code, json=payload, request=request)


@pytest.mark.asyncio
async def test_check_openrouter_key_health_blocks_exhausted_key(monkeypatch):
    response = _response(
        200,
        {"data": {"limit": 1, "limit_remaining": 0, "limit_reset": "monthly"}},
    )
    monkeypatch.setattr(
        openrouter_vision.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(response=response, **kwargs),
    )
    monkeypatch.setattr(openrouter_vision.settings, "OPENROUTER_API_KEY", "test-key")

    log = _Log()

    assert await openrouter_vision.check_openrouter_key_health(log) is False
    assert any("limit exhausted" in message for level, message in log.messages if level == "error")


@pytest.mark.asyncio
async def test_check_openrouter_key_health_allows_unlimited_key(monkeypatch):
    response = _response(
        200,
        {"data": {"limit": None, "limit_remaining": None, "limit_reset": None}},
    )
    monkeypatch.setattr(
        openrouter_vision.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(response=response, **kwargs),
    )
    monkeypatch.setattr(openrouter_vision.settings, "OPENROUTER_API_KEY", "test-key")

    assert await openrouter_vision.check_openrouter_key_health(_Log()) is True


@pytest.mark.asyncio
async def test_check_openrouter_key_health_fails_open_when_probe_unavailable(monkeypatch):
    error = httpx.ConnectError(
        "unavailable",
        request=httpx.Request("GET", "https://openrouter.ai/api/v1/key"),
    )
    monkeypatch.setattr(
        openrouter_vision.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(error=error, **kwargs),
    )
    monkeypatch.setattr(openrouter_vision.settings, "OPENROUTER_API_KEY", "test-key")

    assert await openrouter_vision.check_openrouter_key_health(_Log()) is True


def test_is_exhausted_key_limit_ignores_unlimited_or_unknown_values():
    assert openrouter_vision._is_exhausted_key_limit(None, None) is False
    assert openrouter_vision._is_exhausted_key_limit(1, "not-a-number") is False
    assert openrouter_vision._is_exhausted_key_limit(1, 0) is True
