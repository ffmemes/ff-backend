from datetime import timedelta
from typing import Optional

import orjson
import redis.asyncio as aioredis

from src.config import settings
from src.models import CustomModel

pool = aioredis.ConnectionPool.from_url(
    str(settings.REDIS_URL), max_connections=10, decode_responses=True
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


async def get_all_memes_in_queue_by_key(key: str) -> list[dict]:
    memes = await redis_client.smembers(key)
    return [orjson.loads(meme) for meme in memes]


async def pop_meme_from_queue_by_key(key: str) -> dict | None:
    meme = await redis_client.spop(key)
    return orjson.loads(meme) if meme else None


async def get_meme_queue_length_by_key(key: str) -> int:
    return await redis_client.scard(key)


async def add_memes_to_queue_by_key(key: str, memes: list[dict]) -> int:
    jsoned_memes = [orjson.dumps(meme) for meme in memes]
    # TODO: add ttl, probably using redis transactions
    return await redis_client.sadd(key, *jsoned_memes)


def get_user_info_key(user_id: int) -> str:
    return f"user_info:{user_id}"


async def get_user_info_by_key(key: str) -> dict | None:
    user_info = await redis_client.get(key)
    return orjson.loads(user_info) if user_info else None


async def set_user_info_by_key(key: str, user_info: dict) -> None:
    await redis_client.set(key, orjson.dumps(user_info), ex=60 * 60 * 1)  # 1h cache
