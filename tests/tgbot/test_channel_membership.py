"""Membership races and accounting, against an isolated PostgreSQL test database."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from telegram import Chat, ChatMemberLeft, ChatMemberMember, ChatMemberUpdated, Update, User
from telegram.error import BadRequest, RetryAfter

from src.database import engine, user, user_channel_membership, user_tg, user_tg_chat_membership
from src.tgbot import channel_membership as service
from src.tgbot.handlers.chat.channel_membership import handle_channel_membership_update
from src.tgbot.repo import channel_membership as repo

SUBJECT, ACTOR, OUTSIDER = 1_670_001, 1_670_002, 1_670_003
CHANNEL = service.OWNED_CHANNELS["tgchannelru"]
WHEN = datetime(2026, 9, 5, 12)


@pytest_asyncio.fixture(autouse=True)
async def membership_data():
    async with engine.begin() as conn:
        await conn.execute(
            insert(user).values(
                [
                    {"id": SUBJECT, "type": "user"},
                    {"id": ACTOR, "type": "user"},
                ]
            )
        )
        await conn.execute(insert(user_tg).values(id=SUBJECT, first_name="Test"))
    yield
    async with engine.begin() as conn:
        await conn.execute(delete(user).where(user.c.id.in_([SUBJECT, ACTOR, OUTSIDER])))
        await conn.execute(delete(user_tg).where(user_tg.c.id == SUBJECT))


async def cached(uid=SUBJECT):
    async with engine.connect() as conn:
        row = await conn.execute(
            select(user_channel_membership).where(
                user_channel_membership.c.user_id == uid,
                user_channel_membership.c.chat_id == CHANNEL,
            )
        )
        result = row.mappings().first()
        return dict(result) if result else None


def fake_member(state, uid=SUBJECT):
    return SimpleNamespace(status=state, user=SimpleNamespace(id=uid, is_bot=False))


async def event(state="member", when=WHEN, update_id=10, was_member=False, **kwargs):
    return await repo.persist_event(SUBJECT, CHANNEL, state, was_member, when, update_id, **kwargs)


async def test_event_uses_subject_does_not_touch_actor_activity_or_register_outsider():
    changed = User(SUBJECT, "Changed", False)
    actor = User(ACTOR, "Admin", False)
    change = ChatMemberUpdated(
        Chat(CHANNEL, "channel"),
        actor,
        WHEN.replace(tzinfo=timezone.utc),
        ChatMemberLeft(changed),
        ChatMemberMember(changed),
    )
    with patch("src.tgbot.handlers.chat.channel_membership.settings") as settings:
        settings.CHANNEL_MEMBERSHIP_SYNC_ENABLED = True
        await handle_channel_membership_update(Update(10, chat_member=change), SimpleNamespace())
    assert (await cached())["status"] == "member"
    assert await cached(ACTOR) is None
    assert not await repo.persist_event(OUTSIDER, CHANNEL, "member", False, WHEN, 11)
    async with engine.connect() as conn:
        users = (await conn.execute(select(user).where(user.c.id.in_([SUBJECT, ACTOR])))).mappings()
        assert all(row["last_active_at"] is None for row in users)
        assert (await conn.execute(select(user).where(user.c.id == OUTSIDER))).first() is None


async def test_unowned_channel_never_enters_cache():
    assert not await service.record_channel_membership_event(
        user_id=SUBJECT,
        chat_id=-999,
        old_member=fake_member("left"),
        new_member=fake_member("member"),
        event_at=WHEN,
        update_id=1,
    )
    assert await cached() is None


async def test_old_events_and_duplicate_deliveries_cannot_undo_leave():
    assert await event()
    assert await event("nonmember", WHEN + timedelta(seconds=1), 11, True)
    assert not await event("member", WHEN, 10)
    assert not await event("member", WHEN + timedelta(seconds=1), 10)
    row = await cached()
    assert row["status"] == "nonmember"
    assert row["ever_member"]
    assert row["last_event_update_id"] == 11


async def test_same_second_events_use_update_id_and_preserve_prior_positive():
    assert await event("nonmember", update_id=10, was_member=True)
    assert await event("member", update_id=11)
    assert not await event("nonmember", update_id=10)
    assert (await cached())["status"] == "member"


async def test_concurrent_snapshot_cannot_undo_event_received_after_request_start():
    requested = WHEN + timedelta(microseconds=500_000)
    await event("member", WHEN + timedelta(seconds=1), received_at=WHEN + timedelta(seconds=2))
    assert not await repo.persist_snapshot(
        SUBJECT,
        CHANNEL,
        "nonmember",
        requested,
        finished_at=WHEN + timedelta(seconds=3),
    )
    assert (await cached())["status"] == "member"


async def test_delayed_event_wins_same_second_snapshot():
    await repo.persist_snapshot(SUBJECT, CHANNEL, "nonmember", WHEN + timedelta(microseconds=500))
    assert await event("member", WHEN, received_at=WHEN + timedelta(seconds=2))
    assert (await cached())["status"] == "member"


async def test_older_http_response_cannot_undo_newer_snapshot_in_same_second():
    newer = WHEN + timedelta(microseconds=800_000)
    await repo.persist_snapshot(SUBJECT, CHANNEL, "member", newer)
    assert not await repo.persist_snapshot(
        SUBJECT,
        CHANNEL,
        "nonmember",
        WHEN + timedelta(microseconds=100_000),
    )
    assert (await cached())["status"] == "member"


async def test_unknown_api_result_is_not_nonmembership_and_keeps_history():
    await event()
    await repo.persist_snapshot(
        SUBJECT, CHANNEL, "unknown", WHEN + timedelta(days=1), error="BadRequest"
    )
    row = await cached()
    assert row["status"] == "unknown"
    assert row["last_error"] == "BadRequest"
    assert row["ever_member"]


async def test_legacy_positive_is_seeded_and_leave_does_not_delete_it():
    async with engine.begin() as conn:
        await conn.execute(
            insert(user_tg_chat_membership).values(
                user_tg_id=SUBJECT,
                chat_id=CHANNEL,
                last_seen_at=WHEN,
            )
        )
    await repo.persist_snapshot(SUBJECT, CHANNEL, "nonmember", WHEN + timedelta(days=1))
    assert (await cached())["ever_member"]
    async with engine.connect() as conn:
        old = (await conn.execute(select(user_tg_chat_membership))).mappings().one()
        assert old["last_seen_at"] == WHEN


async def test_new_positive_is_read_compatible_without_creating_tg_users():
    await event()
    await repo.persist_event(ACTOR, CHANNEL, "member", False, WHEN, 11)
    async with engine.connect() as conn:
        old = (await conn.execute(select(user_tg_chat_membership))).mappings().all()
        assert len(old) == 1 and old[0]["user_tg_id"] == SUBJECT
        assert (await conn.execute(select(user_tg).where(user_tg.c.id == ACTOR))).first() is None


async def test_missing_users_are_background_backlog_and_fresh_records_are_skipped():
    due = await repo.due_memberships((CHANNEL,), limit=10, active_days=30)
    assert {SUBJECT, ACTOR} <= {row["user_id"] for row in due}
    await repo.persist_snapshot(SUBJECT, CHANNEL, "nonmember", repo.utc_naive())
    due = await repo.due_memberships((CHANNEL,), limit=10, active_days=30)
    assert ACTOR in {row["user_id"] for row in due}
    assert SUBJECT not in {row["user_id"] for row in due}


async def test_loss_of_bot_administration_invalidates_nonmember_cache():
    await repo.persist_snapshot(SUBJECT, CHANNEL, "nonmember", WHEN)
    await repo.invalidate_channel(CHANNEL, when=WHEN + timedelta(seconds=5))
    row = await cached()
    assert row["status"] == "unknown"
    assert row["source"] == "access_lost"


async def test_dry_run_never_calls_telegram_or_mutates_cache():
    bot = AsyncMock()
    result = await service.repair_channel_memberships(bot, limit=10)
    assert result["mode"] == "dry_run" and result["due_pairs"] >= 4
    assert not bot.mock_calls
    assert await cached() is None


async def test_wrong_bot_identity_stops_before_member_requests_or_writes():
    bot = AsyncMock()
    bot.get_me.return_value = SimpleNamespace(username="wrongbot", id=10)
    with pytest.raises(ValueError, match="identity"):
        await service.repair_channel_memberships(bot, apply=True, request_interval=0)
    bot.get_chat_member.assert_not_awaited()
    assert await cached() is None


async def test_member_api_error_becomes_unknown():
    bot = AsyncMock()
    bot.get_me.return_value = SimpleNamespace(username="ffmemesbot", id=10)
    bot.get_chat_member.side_effect = [
        fake_member("administrator", 10),
        fake_member("administrator", 10),
        BadRequest("lookup failed"),
    ]
    with patch.object(
        repo,
        "due_memberships",
        AsyncMock(
            return_value=[
                {"user_id": SUBJECT, "chat_id": CHANNEL},
            ]
        ),
    ):
        result = await service.repair_channel_memberships(bot, apply=True, request_interval=0)
    assert result["statuses"] == {"unknown": 1}
    assert (await cached())["status"] == "unknown"


async def test_retry_after_defers_shared_worker_without_shortened_retry():
    bot = AsyncMock()
    bot.get_me.side_effect = RetryAfter(900)
    result = await service.repair_channel_memberships(bot, apply=True, request_interval=0)
    assert result["retry_after_seconds"] == 900
    bot.get_me.assert_awaited_once()
    client = AsyncMock()
    client.exists.return_value = False
    client.set.return_value = True
    with (
        patch.object(service.redis, "redis_client", client),
        patch.object(
            service,
            "repair_channel_memberships",
            AsyncMock(return_value=result),
        ),
    ):
        assert await service.run_membership_repair_batch(bot, apply=True) == result
    client.set.assert_any_await(service._COOLDOWN_KEY, "1", ex=900)
    assert client.eval.await_count == 1


async def test_worker_cancellation_releases_only_its_lease():
    client = AsyncMock()
    client.exists.return_value = False
    client.set.return_value = True
    with (
        patch.object(service.redis, "redis_client", client),
        patch.object(
            service,
            "repair_channel_memberships",
            AsyncMock(side_effect=asyncio.CancelledError),
        ),
    ):
        with pytest.raises(asyncio.CancelledError):
            await service.run_membership_repair_batch(AsyncMock(), apply=True)
    lease_token = client.set.await_args.args[1]
    client.eval.assert_awaited_once_with(service._RELEASE_LEASE, 1, service._LEASE_KEY, lease_token)


@pytest.mark.parametrize(
    "is_member,expected", [(True, "member"), (False, "nonmember"), (None, "unknown")]
)
def test_restricted_status_is_not_automatically_a_subscriber(is_member, expected):
    assert (
        service.membership_status(
            SimpleNamespace(
                status="restricted",
                is_member=is_member,
            )
        )
        == expected
    )
