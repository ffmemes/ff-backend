from types import SimpleNamespace

import pytest

from src.flows.crossposting import editorial


class _FailingBot:
    async def send_photo(self, **_kwargs):
        raise AssertionError("send_photo must not be called for invalid media input")


class _Logger:
    def info(self, *_args, **_kwargs):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"photo_file_id": ""}, "photo_file_id must not be empty"),
        ({"photo_url": "   "}, "photo_url must not be empty"),
        ({"photo_bytes": b""}, "photo_bytes must not be empty"),
    ],
)
async def test_post_editorial_rejects_empty_media_before_sending(monkeypatch, kwargs, message):
    monkeypatch.setattr(editorial, "bot", _FailingBot())
    monkeypatch.setattr(editorial, "get_run_logger", lambda: _Logger())

    with pytest.raises(ValueError, match=message):
        await editorial.post_editorial_to_channel.fn(
            text="<b>ok</b>",
            channel="ffmemes",
            **kwargs,
        )


@pytest.mark.asyncio
async def test_post_editorial_sends_raw_bytes_with_filename(monkeypatch):
    calls = []

    class Bot:
        async def send_photo(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(message_id=123)

    monkeypatch.setattr(editorial, "bot", Bot())
    monkeypatch.setattr(editorial, "get_run_logger", lambda: _Logger())

    message_id = await editorial.post_editorial_to_channel.fn(
        text="<b>ok</b>",
        channel="ffmemes",
        photo_bytes=b"\x89PNG\r\n\x1a\n",
    )

    assert message_id == 123
    assert calls[0]["photo"] == b"\x89PNG\r\n\x1a\n"
    assert calls[0]["filename"] == "editorial.png"
