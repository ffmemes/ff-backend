from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.flows.storage import describe_memes
from src.flows.storage.openrouter_vision import run_attempt_cap


class _Log:
    def __init__(self):
        self.messages = []

    def warning(self, message, *args):
        self.messages.append(message % args if args else message)

    info = warning


@pytest.mark.asyncio
async def test_flow_emits_observable_no_work_when_no_ocr_key_is_configured(monkeypatch):
    events = []
    log = _Log()
    monkeypatch.setattr(describe_memes, "get_run_logger", lambda: log)
    monkeypatch.setattr(describe_memes, "get_configured_openrouter_keys", lambda: ())
    monkeypatch.setattr(describe_memes, "safe_emit", lambda *args: events.append(args))

    state = await describe_memes.describe_memes_flow.fn()

    assert events == [
        ("ff.describe_memes.no_work", "ff.describe_memes", {"reason": "no_configured_key"})
    ]
    assert "No work performed" in log.messages[0]
    assert state.name == "OCR unavailable"
    assert state.message == "no OpenRouter OCR key is configured"


@pytest.mark.asyncio
async def test_flow_emits_observable_no_work_when_all_keys_are_unusable(monkeypatch):
    events = []
    log = _Log()
    monkeypatch.setattr(describe_memes, "get_run_logger", lambda: log)
    monkeypatch.setattr(describe_memes, "get_configured_openrouter_keys", lambda: (object(),))

    async def no_usable_keys(_log):
        return ()

    monkeypatch.setattr(describe_memes, "get_usable_openrouter_keys", no_usable_keys)
    monkeypatch.setattr(describe_memes, "safe_emit", lambda *args: events.append(args))

    state = await describe_memes.describe_memes_flow.fn()

    assert events == [
        ("ff.describe_memes.no_work", "ff.describe_memes", {"reason": "no_usable_key"})
    ]
    assert "No work performed" in log.messages[0]
    assert state.name == "OCR unavailable"
    assert state.message == "no usable OpenRouter OCR key"


def test_run_attempt_cap_spreads_remaining_budget_over_runs_left():
    keys = (SimpleNamespace(account_id="a", daily_budget=900),) * 2 + (
        SimpleNamespace(account_id="b", daily_budget=900),
    )
    midnight = datetime(2026, 10, 30, tzinfo=timezone.utc)
    noon = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)

    assert run_attempt_cap(keys, 0, midnight) == 19  # ceil(1800 / 96)
    assert run_attempt_cap(keys, 1200, noon) == 13  # ceil(600 / 48)
    assert run_attempt_cap(keys, 1800, noon) == 0


@pytest.mark.asyncio
async def test_flow_stops_when_run_attempt_cap_is_used(monkeypatch):
    log = _Log()
    used = {"n": 100}
    described = []

    async def fake_used_today():
        return used["n"]

    async def fake_describe(meme_row, _log, **_kwargs):
        described.append(meme_row["id"])
        used["n"] += 2  # primary model failed, fallback succeeded
        return "ok"

    async def usable(_log):
        return ("key",)

    async def memes(limit):
        return [{"id": i, "ocr_result": None} for i in range(limit)]

    async def no_sleep(_s):
        return None

    monkeypatch.setattr(describe_memes, "get_run_logger", lambda: log)
    monkeypatch.setattr(describe_memes, "get_configured_openrouter_keys", lambda: ("key",))
    monkeypatch.setattr(describe_memes, "get_usable_openrouter_keys", usable)
    monkeypatch.setattr(describe_memes, "get_memes_to_describe", memes)
    monkeypatch.setattr(describe_memes, "get_free_requests_used_today", fake_used_today)
    monkeypatch.setattr(describe_memes, "run_attempt_cap", lambda *_a: 5)
    monkeypatch.setattr(describe_memes, "describe_single_meme", fake_describe)
    monkeypatch.setattr(describe_memes.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(describe_memes, "safe_emit", lambda *args: None)

    await describe_memes.describe_memes_flow.fn(batch_size=18)

    assert described == [0, 1, 2]  # 6 attempts >= cap 5 after the third meme
