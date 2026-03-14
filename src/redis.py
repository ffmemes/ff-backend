import logging
from datetime import timedelta
from typing import Optional

import orjson

from redis import asyncio as aioredis
from redis.exceptions import ResponseError
from src.config import settings
from src.models import CustomModel

logger = logging.getLogger(__name__)

pool = aioredis.ConnectionPool.from_url(
    str(settings.REDIS_URL),
    max_connections=settings.REDIS_MAX_CONNECTIONS,
    health_check_interval=settings.REDIS_HEALTH_CHECK_INTERVAL,
    socket_keepalive=True,
    decode_responses=True,
)
redis_client = aioredis.Redis(connection_pool=pool)


class RedisData(CustomModel):
    key: bytes | str
    value: bytes | str
    ttl: Optional[int | timedelta] = None


async def set_redis_key(redis_data: RedisData, *, is_transaction: bool = False) -> None:
    async with redis_client.pipeline(transaction=is_transaction) as pipe:
        await pipe.set(redis_data.key, redis_data.value)
        if redis_data.ttl:
            await pipe.expire(redis_data.key, redis_data.ttl)

        await pipe.execute()


async def get_by_key(key: str) -> Optional[str]:
    return await redis_client.get(key)


async def delete_by_key(key: str) -> None:
    return await redis_client.delete(key)


def get_meme_queue_key(user_id: int) -> str:
    return f"meme_queue:{user_id}"


async def _delete_if_wrong_type(key: str) -> None:
    """Delete a key if it exists with wrong type (SET->LIST migration)."""
    try:
        await redis_client.delete(key)
    except Exception:
        pass


async def get_all_memes_in_queue_by_key(key: str) -> list[dict]:
    try:
        memes = await redis_client.lrange(key, 0, -1)
    except ResponseError:
        await _delete_if_wrong_type(key)
        return []
    return [orjson.loads(meme) for meme in memes]


async def pop_meme_from_queue_by_key(key: str) -> dict | None:
    try:
        meme = await redis_client.lpop(key)
    except ResponseError:
        await _delete_if_wrong_type(key)
        return None
    return orjson.loads(meme) if meme else None


async def clear_meme_queue_by_key(key: str) -> None:
    await redis_client.delete(key)


async def get_meme_queue_length_by_key(key: str) -> int:
    try:
        return await redis_client.llen(key)
    except ResponseError:
        await _delete_if_wrong_type(key)
        return 0


async def add_memes_to_queue_by_key(key: str, memes: list[dict], expire: int = 3600) -> None:
    jsoned_memes = [orjson.dumps(meme) for meme in memes]
    try:
        async with redis_client.pipeline(transaction=True) as pipe:
            await pipe.rpush(key, *jsoned_memes)
            await pipe.expire(key, expire)
            await pipe.execute(raise_on_error=True)
    except ResponseError:
        await _delete_if_wrong_type(key)
        async with redis_client.pipeline(transaction=True) as pipe:
            await pipe.rpush(key, *jsoned_memes)
            await pipe.expire(key, expire)
            await pipe.execute(raise_on_error=True)


def get_user_info_key(user_id: int) -> str:
    return f"user_info:{user_id}"


async def get_user_info_by_key(key: str) -> dict | None:
    user_info = await redis_client.get(key)
    return orjson.loads(user_info) if user_info else None


async def set_user_info_by_key(key: str, user_info: dict) -> None:
    await redis_client.set(key, orjson.dumps(user_info), ex=60 * 60 * 1)  # 1h cache


#############################
# wrapped


def get_user_wrapped_key(user_id: int) -> str:
    return f"wrapped:{user_id}"


async def get_user_wrapped(user_id: str) -> dict | None:
    data = await redis_client.get(get_user_wrapped_key(user_id))
    return orjson.loads(data) if data else None


async def set_user_wrapped(user_id: str, data: dict) -> None:
    await redis_client.set(get_user_wrapped_key(user_id), orjson.dumps(data))
