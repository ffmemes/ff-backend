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


def _src_rows():
    return [
        {
            "id": 1,
            "post_id": 11,
            "source_id": 5,
            "url": "https://t.me/a",
            "peer_id": None,
            "peer_hash": None,
        },
        {
            "id": 2,
            "post_id": 21,
            "source_id": 6,
            "url": "https://t.me/b",
            "peer_id": 77,
            "peer_hash": 88,
        },
        {
            "id": 3,
            "post_id": 31,
            "source_id": 7,
            "url": "https://t.me/c",
            "peer_id": None,
            "peer_hash": None,
        },
    ]


@pytest.mark.asyncio
async def test_source_post_stats_skips_failures_and_writes_rest(monkeypatch):
    from telethon.tl.types import InputPeerChannel

    class Client:
        async def get_input_entity(self, name):
            if name == "a":
                raise ValueError("no such channel")
            return InputPeerChannel(9, 10)

        async def get_messages(self, entity, ids=None):
            if ids == [21]:
                return [None]  # deleted post
            return [SimpleNamespace(views=500, forwards=7, reactions=None, replies=None)]

    execute = AsyncMock()
    monkeypatch.setattr(stats_collector, "fetch_all", AsyncMock(return_value=_src_rows()))
    monkeypatch.setattr(stats_collector, "execute", execute)
    monkeypatch.setattr(stats_collector, "get_run_logger", lambda: _FakeLog())
    monkeypatch.setattr(stats_collector.asyncio, "sleep", AsyncMock())

    assert await stats_collector._collect_source_post_stats(Client()) == 2
    updates = [c.args[1] for c in execute.await_args_list if "fwds" in c.args[1]]
    assert updates == [
        {"ids": [2], "fwds": [None]},
        {"ids": [3], "fwds": [7]},
    ]
    # source c was resolved by username → peer cached
    assert any(c.args[1].get("id") == 7 and "peer" in c.args[1] for c in execute.await_args_list)


@pytest.mark.asyncio
async def test_source_post_stats_stops_on_long_flood_wait(monkeypatch):
    from telethon.errors import FloodWaitError

    calls = []

    class Client:
        async def get_input_entity(self, name):
            calls.append(name)
            raise FloodWaitError(None, capture=600)

    monkeypatch.setattr(stats_collector, "fetch_all", AsyncMock(return_value=_src_rows()))
    monkeypatch.setattr(stats_collector, "execute", AsyncMock())
    monkeypatch.setattr(stats_collector, "get_run_logger", lambda: _FakeLog())
    sleep = AsyncMock()
    monkeypatch.setattr(stats_collector.asyncio, "sleep", sleep)

    assert await stats_collector._collect_source_post_stats(Client()) == 0
    assert calls == ["a"]  # stopped after the first long flood wait, no 600s sleep
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_source_post_stats_sql_roundtrip(monkeypatch):
    """Real DB: picks 20–48h posts, writes forwards (not views), caches the peer, then idles."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import text
    from telethon.tl.types import InputPeerChannel

    from src.database import engine, fetch_all

    class Client:
        async def get_input_entity(self, name):
            return InputPeerChannel(123, 456)

        async def get_messages(self, entity, ids=None):
            msg = SimpleNamespace(views=900, forwards=9, reactions=None, replies=None)
            return [None] + [msg] * (len(ids) - 1)

    monkeypatch.setattr(stats_collector, "get_run_logger", lambda: _FakeLog())
    monkeypatch.setattr(stats_collector.asyncio, "sleep", AsyncMock())
    now = datetime.now(UTC).replace(tzinfo=None)
    async with engine.connect() as conn:
        await conn.execute(
            text(
                "INSERT INTO meme_source (id, type, url, status) "
                "VALUES (19900, 'telegram', 'https://t.me/zz', 'parsing_enabled')"
            )
        )
        for i, age_h in enumerate([30, 30, 5]):  # last one too young
            await conn.execute(
                text(
                    "INSERT INTO meme_raw_telegram (id, meme_source_id, post_id, url, date, views) "
                    "VALUES (:id, 19900, :p, 'u', :d, 5)"
                ),
                {"id": 19900 + i, "p": i, "d": now - timedelta(hours=age_h)},
            )
        await conn.commit()
    try:
        assert await stats_collector._collect_source_post_stats(Client()) == 2
        rows = await fetch_all(
            text(
                "SELECT views, forwards, stats_fetched_at IS NOT NULL AS done "
                "FROM meme_raw_telegram WHERE meme_source_id = 19900 ORDER BY id"
            )
        )
        assert [tuple(r.values()) for r in rows] == [
            (5, None, True),  # message gone: views kept, forwards NULL
            (5, 9, True),  # views stay the parser value
            (5, None, False),
        ]
        src = await fetch_all(text("SELECT data FROM meme_source WHERE id = 19900"))
        assert src[0]["data"]["tg_peer"] == {"id": 123, "hash": 456}
        assert await stats_collector._collect_source_post_stats(Client()) == 0
    finally:
        async with engine.connect() as conn:
            await conn.execute(text("DELETE FROM meme_source WHERE id = 19900"))
            await conn.commit()


@pytest.mark.asyncio
async def test_channel_sweep_survives_source_stats_crash(monkeypatch):
    class Client:
        async def disconnect(self):
            pass

    monkeypatch.setattr(stats_collector, "_with_telethon_client", AsyncMock(return_value=Client()))
    monkeypatch.setattr(stats_collector, "_collect_post_stats", AsyncMock())
    monkeypatch.setattr(stats_collector, "_collect_subscriber_count", AsyncMock())
    monkeypatch.setattr(
        stats_collector, "_collect_source_post_stats", AsyncMock(side_effect=RuntimeError("boom"))
    )
    monkeypatch.setattr(stats_collector, "get_run_logger", lambda: _FakeLog())

    await stats_collector.collect_channel_stats.fn()
    stats_collector._collect_post_stats.assert_awaited()
