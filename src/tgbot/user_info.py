"""
    Cache user info in redis
"""
from collections import defaultdict

from src import redis
from src.tgbot import service


async def get_cached_user_info(user_id: int) -> dict | None:
    key = redis.get_user_info_key(user_id)
    user_info = await redis.get_user_info_by_key(key)
    if user_info is None:
        return None

    return user_info


async def cache_user_info(user_id: int, user_info: dict):
    key = redis.get_user_info_key(user_id)
    await redis.set_user_info_by_key(key, user_info)


async def update_user_info_cache(user_id: int) -> defaultdict:
    user_info = await service.get_user_info(user_id)
    await cache_user_info(user_id, user_info)
    if user_info is None:
        raise Exception(f"Can't get_user_info({user_id}). Probably no data in db.")

    return defaultdict(lambda: None, **user_info)


async def get_user_info(user_id: int) -> defaultdict:
    user_info = await get_cached_user_info(user_id)
    if user_info is None:
        user_info = await update_user_info_cache(user_id)

    return defaultdict(lambda: None, **user_info)


async def update_user_info_counters(user_id: int):
    user_info = await get_user_info(user_id)
    user_info["nmemes_sent"] += 1
    user_info["memes_watched_today"] += 1
    await cache_user_info(user_id, user_info)
