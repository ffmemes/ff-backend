from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.flows.crossposting import stats_collector


class _FakeLog:
    def info(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


class _FakeAdminLog:
    def __init__(self, events):
        self._events = events

    def __aiter__(self):
        self._iter = iter(self._events)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _FakeClient:
    def __init__(self, events):
        self.events = events
        self.iter_kwargs = None

    async def get_entity(self, channel_username):
        return SimpleNamespace(username=channel_username)

    def iter_admin_log(self, entity, **kwargs):
        self.iter_kwargs = kwargs
        return _FakeAdminLog(self.events)


def _event(
    event_id: int,
    *,
    user_id: int,
    joined: bool = False,
    joined_invite: bool = False,
    left: bool = False,
    participant_user_id: int | None = None,
    action_name: str = "FakeAction",
):
    participant = (
        SimpleNamespace(user_id=participant_user_id) if participant_user_id is not None else None
    )
    action = type(action_name, (), {})()
    return SimpleNamespace(
        id=event_id,
        user_id=user_id,
        joined=joined,
        joined_invite=joined_invite,
        left=left,
        date=datetime(2026, 6, 1, 9, 30, tzinfo=timezone(timedelta(hours=3))),
        new=participant,
        action=action,
    )


def test_normalize_public_join_converts_timestamp_to_naive_utc() -> None:
    row = stats_collector._normalize_channel_lifecycle_event(
        "tgchannelru",
        _event(101, user_id=20001, joined=True),
    )

    assert row["channel"] == "tgchannelru"
    assert row["telegram_event_id"] == 101
    assert row["telegram_user_id"] == 20001
    assert row["event_type"] == "join"
    assert row["event_at"] == datetime(2026, 6, 1, 6, 30)
    assert row["data"]["join_source"] == "public"


def test_normalize_invite_join_prefers_participant_user_id() -> None:
    row = stats_collector._normalize_channel_lifecycle_event(
        "tgchannelen",
        _event(102, user_id=30001, joined_invite=True, participant_user_id=40001),
    )

    assert row["telegram_user_id"] == 40001
    assert row["event_type"] == "join"
    assert row["data"]["actor_user_id"] == 30001
    assert row["data"]["join_source"] == "invite"


def test_normalize_invite_link_join_from_action_name() -> None:
    row = stats_collector._normalize_channel_lifecycle_event(
        "tgchannelen",
        _event(
            104,
            user_id=40002,
            action_name="ChannelAdminLogEventActionParticipantJoinByInvite",
        ),
    )

    assert row["telegram_user_id"] == 40002
    assert row["event_type"] == "join"
    assert row["data"]["join_source"] == "invite_link"


def test_normalize_leave_records_leaving_user() -> None:
    row = stats_collector._normalize_channel_lifecycle_event(
        "tgchannelru",
        _event(103, user_id=20002, left=True),
    )

    assert row["telegram_user_id"] == 20002
    assert row["event_type"] == "leave"
    assert row["data"]["join_source"] is None


@pytest.mark.asyncio
async def test_collect_channel_lifecycle_events_dedupes_at_insert(monkeypatch) -> None:
    executed = []

    async def fake_execute(statement):
        executed.append(statement)
        return SimpleNamespace(rowcount=1 if len(executed) == 1 else 0)

    async def fake_fetch_one(statement, params):
        assert "max(telegram_event_id)" in str(statement)
        assert params == {"channel": "tgchannelru"}
        return None

    monkeypatch.setattr(stats_collector, "execute", fake_execute)
    monkeypatch.setattr(stats_collector, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(stats_collector, "get_run_logger", lambda: _FakeLog())

    client = _FakeClient(
        [
            _event(101, user_id=20001, joined=True),
            _event(101, user_id=20001, joined=True),
        ]
    )

    inserted = await stats_collector._collect_channel_lifecycle_events(
        client,
        "tgchannelru",
        "fastfoodmemes",
        limit=25,
    )

    assert inserted == 1
    assert len(executed) == 2
    assert client.iter_kwargs == {
        "limit": 25,
        "min_id": 0,
        "join": True,
        "leave": True,
        "invite": True,
    }
    assert "ON CONFLICT (channel, telegram_event_id) DO NOTHING" in str(executed[0])


@pytest.mark.asyncio
async def test_collect_channel_lifecycle_events_uses_high_water_mark(monkeypatch) -> None:
    async def fake_execute(statement):
        return SimpleNamespace(rowcount=1)

    async def fake_fetch_one(statement, params):
        return {"max_event_id": 900}

    monkeypatch.setattr(stats_collector, "execute", fake_execute)
    monkeypatch.setattr(stats_collector, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(stats_collector, "get_run_logger", lambda: _FakeLog())

    client = _FakeClient([_event(901, user_id=20001, joined=True)])

    inserted = await stats_collector._collect_channel_lifecycle_events(
        client,
        "tgchannelru",
        "fastfoodmemes",
        limit=25,
    )

    assert inserted == 1
    assert client.iter_kwargs["min_id"] == 900
    assert client.iter_kwargs["limit"] is None


@pytest.mark.asyncio
async def test_channel_lifecycle_readout_uses_days_window(monkeypatch) -> None:
    calls = []

    async def fake_fetch_all(statement, params):
        calls.append((str(statement), params))
        return [{"channel": "tgchannelru", "joins": 3, "leaves": 1}]

    monkeypatch.setattr(stats_collector, "fetch_all", fake_fetch_all)

    rows = await stats_collector.get_channel_lifecycle_readout(days=14)

    assert rows == [{"channel": "tgchannelru", "joins": 3, "leaves": 1}]
    sql, params = calls[0]
    assert "channel_lifecycle_event" in sql
    assert "new_bot_sessions_within_24h_after_join" in sql
    assert params == {"days": 14}
