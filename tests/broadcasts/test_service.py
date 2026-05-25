from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete
from tests.factories import create_user, create_user_language

from src.broadcasts.service import get_all_non_blocked_users, get_users_with_language
from src.database import engine, user, user_language, user_tg

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
