import asyncio
import uuid

from src import redis

UPDATE_USER_LOCK_TTL_SECONDS = 120
UPDATE_USER_LOCK_POLL_SECONDS = 0.05
_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""


async def acquire_update_user_lock(user_id: int) -> tuple[str, str]:
    """Serialize webhook updates for one Telegram user across Gunicorn workers."""
    lock_key = f"tg_update_user_lock:{user_id}"
    token = str(uuid.uuid4())

    while True:
        acquired = await redis.redis_client.set(
            lock_key,
            token,
            nx=True,
            ex=UPDATE_USER_LOCK_TTL_SECONDS,
        )
        if acquired:
            return lock_key, token

        await asyncio.sleep(UPDATE_USER_LOCK_POLL_SECONDS)


async def release_update_user_lock(lock: tuple[str, str] | None) -> None:
    if lock is None:
        return

    lock_key, token = lock
    await redis.redis_client.eval(_RELEASE_LOCK_SCRIPT, 1, lock_key, token)
