from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import delete
from tests.factories import create_user, create_user_language

from src.broadcasts.service import (
    get_all_non_blocked_users,
    get_users_inactive_since_days,
    get_users_with_language,
    send_meme_broadcast,
)
from src.database import engine, user, user_language, user_tg
from src.storage.constants import MemeType
from src.storage.schemas import MemeData

ACTIVE_USER_ID = 311001
BLOCKED_ADMIN_ID = 311002
LEGACY_BLOCKED_USER_ID = 311003
WAITLIST_USER_ID = 311004
ACTIVE_ADMIN_ID = 311005
TEST_USER_IDS = (
    ACTIVE_USER_ID,
    BLOCKED_ADMIN_ID,
    LEGACY_BLOCKED_USER_ID,
    WAITLIST_USER_ID,
    ACTIVE_ADMIN_ID,
)


@pytest_asyncio.fixture()
async def cleanup_broadcast_users():
    await _cleanup()
    yield
    await _cleanup()


async def _cleanup() -> None:
    async with engine.connect() as conn:
        await conn.execute(delete(user_language).where(user_language.c.user_id.in_(TEST_USER_IDS)))
        await conn.execute(delete(user_tg).where(user_tg.c.id.in_(TEST_USER_IDS)))
        await conn.execute(delete(user).where(user.c.id.in_(TEST_USER_IDS)))
        await conn.commit()


@pytest.mark.asyncio
async def test_get_users_with_language_skips_blocked_transport_state(
    cleanup_broadcast_users,
) -> None:
    async with engine.connect() as conn:
        await create_user(conn, id=ACTIVE_USER_ID)
        await create_user(conn, id=BLOCKED_ADMIN_ID, type="admin")
        await create_user(conn, id=LEGACY_BLOCKED_USER_ID, type="blocked_bot")
        await create_user(conn, id=WAITLIST_USER_ID, type="waitlist")
        await create_user(conn, id=ACTIVE_ADMIN_ID, type="admin")
        for user_id in TEST_USER_IDS:
            await create_user_language(conn, user_id=user_id, language_code="ru")
        await conn.execute(
            user.update()
            .where(user.c.id == BLOCKED_ADMIN_ID)
            .values(blocked_bot_at=datetime(2026, 5, 25, 12, 0, 0))
        )
        await conn.commit()

    rows = await get_users_with_language("ru")

    assert {row["user_id"] for row in rows if row["user_id"] in TEST_USER_IDS} == {
        ACTIVE_USER_ID,
        ACTIVE_ADMIN_ID,
    }


@pytest.mark.asyncio
async def test_get_all_non_blocked_users_skips_blocked_transport_state(
    cleanup_broadcast_users,
) -> None:
    async with engine.connect() as conn:
        await create_user(conn, id=ACTIVE_USER_ID)
        await create_user(conn, id=BLOCKED_ADMIN_ID, type="admin")
        await create_user(conn, id=LEGACY_BLOCKED_USER_ID, type="blocked_bot")
        await create_user(conn, id=ACTIVE_ADMIN_ID, type="admin")
        for user_id in (
            ACTIVE_USER_ID,
            BLOCKED_ADMIN_ID,
            LEGACY_BLOCKED_USER_ID,
            ACTIVE_ADMIN_ID,
        ):
            await create_user_language(conn, user_id=user_id, language_code="ru")
        await conn.execute(
            user.update()
            .where(user.c.id == BLOCKED_ADMIN_ID)
            .values(blocked_bot_at=datetime(2026, 5, 25, 12, 0, 0))
        )
        await conn.commit()

    rows = await get_all_non_blocked_users()

    assert {row["user_id"] for row in rows if row["user_id"] in TEST_USER_IDS} == {
        ACTIVE_USER_ID,
        ACTIVE_ADMIN_ID,
    }


@pytest.mark.asyncio
async def test_get_users_inactive_since_days_skips_recent_and_blocked(
    cleanup_broadcast_users,
) -> None:
    now = datetime.utcnow()
    idle_id = ACTIVE_USER_ID
    recent_id = ACTIVE_ADMIN_ID
    async with engine.connect() as conn:
        await create_user(conn, id=idle_id)
        await create_user(conn, id=recent_id)
        await create_user(conn, id=WAITLIST_USER_ID, type="waitlist")
        await create_user(conn, id=LEGACY_BLOCKED_USER_ID, type="blocked_bot")
        await conn.execute(
            user.update()
            .where(user.c.id == idle_id)
            .values(last_active_at=now - timedelta(days=10))
        )
        await conn.execute(
            user.update()
            .where(user.c.id == recent_id)
            .values(last_active_at=now - timedelta(days=2))
        )
        await conn.execute(
            user.update()
            .where(user.c.id == WAITLIST_USER_ID)
            .values(last_active_at=now - timedelta(days=20))
        )
        await conn.commit()

    rows = await get_users_inactive_since_days(7)
    ids = {user_id for user_id in rows if user_id in TEST_USER_IDS}
    assert idle_id in ids
    assert recent_id not in ids
    assert WAITLIST_USER_ID not in ids
    assert LEGACY_BLOCKED_USER_ID not in ids


@pytest.mark.asyncio
async def test_send_meme_broadcast_dry_run_does_not_send() -> None:
    pick = AsyncMock()
    send = AsyncMock()
    with (
        patch("src.broadcasts.service.redis_client.scard", AsyncMock(return_value=0)),
        patch("src.recommendations.broadcast_pick.pick_reengagement_meme", pick),
        patch("src.tgbot.senders.meme.send_meme_to_user", send),
    ):
        result = await send_meme_broadcast("test-dry", [1, 2], dry_run=True)

    pick.assert_not_called()
    send.assert_not_called()
    assert result["audience"] == 2
    assert result["sent"] == 0


@pytest.mark.asyncio
async def test_send_meme_broadcast_picks_per_user_and_dedups() -> None:
    meme = MemeData(
        id=11,
        type=MemeType.IMAGE,
        telegram_file_id="f",
        caption=None,
        recommended_by="broadcast_channel_viral",
    )
    pick = AsyncMock(return_value=(meme, "broadcast_channel_viral"))
    send = AsyncMock()
    seen: set[str] = set()

    async def sismember(_key, value):
        return value in seen

    async def sadd(_key, value):
        seen.add(value)
        return 1

    with (
        patch("src.broadcasts.service.redis_client.scard", AsyncMock(return_value=0)),
        patch("src.broadcasts.service.redis_client.sismember", sismember),
        patch("src.broadcasts.service.redis_client.sadd", sadd),
        patch("src.broadcasts.service.bot", object()),
        patch("src.recommendations.broadcast_pick.pick_reengagement_meme", pick),
        patch("src.tgbot.senders.meme.send_meme_to_user", send),
    ):
        result = await send_meme_broadcast("test-real", [7, 8], delay=0)
        result_again = await send_meme_broadcast("test-real", [7, 8], delay=0)

    assert pick.await_count == 2
    assert send.await_count == 2
    assert result["sent"] == 2
    assert send.await_args.kwargs["recommended_by"] == "broadcast_channel_viral"
    assert result_again["skipped"] == 2
    assert result_again["sent"] == 0
