"""Unit tests for crosspost stats persistence + single-msg / young refresh."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.flows.crossposting import stats_collector


class _FakeLog:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


@pytest.mark.asyncio
async def test_persist_crosspost_metrics_writes_snapshot_and_live(monkeypatch):
    calls = []

    async def fake_execute(stmt, params=None):
        calls.append((str(stmt), params))
        return MagicMock(rowcount=1)

    monkeypatch.setattr(stats_collector, "execute", fake_execute)

    await stats_collector._persist_crosspost_metrics(
        channel_key="tgchannelru",
        meme_id=42,
        telegram_message_id=100,
        views=50,
        forwards=3,
        reactions=2,
        comments=0,
        reactions_detail={"❤": 2},
        message_text="hi",
    )

    assert len(calls) == 2
    # second call is the UPDATE with live columns
    _, params = calls[1]
    assert params["views"] == 50
    assert params["fwd"] == 3
    assert params["msg_id"] == 100
    assert params["ch"] == "tgchannelru"


@pytest.mark.asyncio
async def test_refresh_single_message_happy_path(monkeypatch):
    msg = SimpleNamespace(
        id=777,
        views=12,
        forwards=2,
        reactions=SimpleNamespace(results=[]),
        replies=None,
        text="cta",
    )

    class Client:
        async def connect(self):
            pass

        async def disconnect(self):
            pass

        async def is_user_authorized(self):
            return True

        async def get_entity(self, name):
            return SimpleNamespace(username=name)

        async def get_messages(self, entity, ids=None):
            assert ids == 777
            return msg

    monkeypatch.setattr(stats_collector, "_get_telethon_client", lambda: Client())
    monkeypatch.setattr(stats_collector, "get_run_logger", lambda: _FakeLog())
    persist = AsyncMock()
    monkeypatch.setattr(stats_collector, "_persist_crosspost_metrics", persist)

    result = await stats_collector.refresh_crosspost_message_stats("tgchannelru", 777, meme_id=999)

    assert result is not None
    assert result["views"] == 12
    assert result["forwards"] == 2
    persist.assert_awaited_once()
    kwargs = persist.await_args.kwargs
    assert kwargs["meme_id"] == 999
    assert kwargs["telegram_message_id"] == 777


@pytest.mark.asyncio
async def test_refresh_skips_unknown_channel(monkeypatch):
    monkeypatch.setattr(stats_collector, "get_run_logger", lambda: _FakeLog())
    result = await stats_collector.refresh_crosspost_message_stats("nope", 1, 2)
    assert result is None


@pytest.mark.asyncio
async def test_young_collect_uses_id_list(monkeypatch):
    young_rows = [
        {"meme_id": 1, "telegram_message_id": 10},
        {"meme_id": 2, "telegram_message_id": 20},
    ]
    msgs = [
        SimpleNamespace(
            id=10,
            views=1,
            forwards=0,
            reactions=None,
            replies=None,
            text="",
        ),
        SimpleNamespace(
            id=20,
            views=5,
            forwards=1,
            reactions=None,
            replies=None,
            text="",
        ),
    ]

    class Client:
        async def get_entity(self, name):
            return SimpleNamespace(username=name)

        async def get_messages(self, entity, ids=None):
            assert ids == [10, 20]
            return msgs

    monkeypatch.setattr(stats_collector, "fetch_all", AsyncMock(return_value=young_rows))
    monkeypatch.setattr(stats_collector, "get_run_logger", lambda: _FakeLog())
    persist = AsyncMock()
    monkeypatch.setattr(stats_collector, "_persist_crosspost_metrics", persist)

    n = await stats_collector._collect_young_crosspost_stats(
        Client(), "tgchannelru", "fastfoodmemes"
    )
    assert n == 2
    assert persist.await_count == 2


@pytest.mark.asyncio
async def test_safe_refresh_swallows_errors(monkeypatch):
    from src.crossposting.constants import Channel
    from src.flows.crossposting import meme as meme_flow

    monkeypatch.setattr(
        meme_flow,
        "refresh_crosspost_message_stats",
        AsyncMock(side_effect=RuntimeError("boom")),
    )
    log = MagicMock()
    await meme_flow._safe_refresh_crosspost_stats(Channel.TG_CHANNEL_RU, 1, 2, log)
    log.warning.assert_called()
