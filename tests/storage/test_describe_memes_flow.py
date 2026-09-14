import pytest

from src.flows.storage import describe_memes


class _Log:
    def __init__(self):
        self.messages = []

    def warning(self, message, *args):
        self.messages.append(message % args if args else message)


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
