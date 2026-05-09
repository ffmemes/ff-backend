import asyncio

import pytest

from src.tgbot import update_lock


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, token: str, *, nx: bool, ex: int) -> bool:
        assert nx is True
        assert ex == update_lock.UPDATE_USER_LOCK_TTL_SECONDS
        if key in self.values:
            return False
        self.values[key] = token
        return True

    async def eval(self, script: str, numkeys: int, key: str, token: str) -> int:
        assert script == update_lock._RELEASE_LOCK_SCRIPT
        assert numkeys == 1
        if self.values.get(key) != token:
            return 0
        self.values.pop(key, None)
        return 1


@pytest.mark.parametrize("user_id", [12345])
async def test_update_lock_serializes_same_user(monkeypatch, user_id):
    active_updates = 0
    max_active_updates = 0

    async def process_locked_update():
        nonlocal active_updates, max_active_updates

        lock = await update_lock.acquire_update_user_lock(user_id)
        try:
            active_updates += 1
            max_active_updates = max(max_active_updates, active_updates)
            await asyncio.sleep(0.01)
            active_updates -= 1
        finally:
            await update_lock.release_update_user_lock(lock)

    monkeypatch.setattr(update_lock.redis, "redis_client", FakeRedis())

    await asyncio.gather(
        process_locked_update(),
        process_locked_update(),
    )

    assert max_active_updates == 1
