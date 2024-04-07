import random

from src import redis
from src.recommendations.candidates import (
    classic,
    get_best_memes_from_each_source,
    less_seen_meme_and_source,
    like_spread_and_recent_memes,
)
from src.storage.schemas import MemeData
from src.tgbot.user_info import get_user_info


async def get_next_meme_for_user(user_id: int) -> MemeData | None:
    queue_key = redis.get_meme_queue_key(user_id)
    meme_data = await redis.pop_meme_from_queue_by_key(queue_key)

    if not meme_data:
        return None

    return MemeData(**meme_data)


async def has_memes_in_queue(user_id: int) -> bool:
    queue_key = redis.get_meme_queue_key(user_id)
    queue_length = await redis.get_meme_queue_length_by_key(queue_key)
    return queue_length > 0


async def clear_meme_queue_for_user(user_id: int) -> None:
    queue_key = redis.get_meme_queue_key(user_id)
    await redis.delete_by_key(queue_key)


async def check_queue(user_id: int):
    queue_key = redis.get_meme_queue_key(user_id)
    queue_length = await redis.get_meme_queue_length_by_key(queue_key)

    if queue_length <= 2:
        await generate_recommendations(user_id, limit=5)


async def generate_cold_start_recommendations(user_id, limit=10):
    queue_key = redis.get_meme_queue_key(user_id)
    memes_in_queue = await redis.get_all_memes_in_queue_by_key(queue_key)
    meme_ids_in_queue = [meme["id"] for meme in memes_in_queue]

    candidates = await get_best_memes_from_each_source(
        user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
    )
    if len(candidates) == 0:
        return

    await redis.add_memes_to_queue_by_key(queue_key, candidates)


async def generate_recommendations(user_id, limit):
    queue_key = redis.get_meme_queue_key(user_id)
    memes_in_queue = await redis.get_all_memes_in_queue_by_key(queue_key)
    meme_ids_in_queue = [meme["id"] for meme in memes_in_queue]

    user_info = await get_user_info(user_id)

    r = random.random()

    if user_info["nmemes_sent"] < 30:
        candidates = await get_best_memes_from_each_source(
            user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
        )

    elif user_info["nmemes_sent"] < 100:
        if r < 0.5:
            candidates = await get_best_memes_from_each_source(
                user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
            )
        else:
            candidates = await classic(
                user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
            )

    else:
        if r < 0.25:
            candidates = await classic(
                user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
            )
        elif r < 0.5:
            candidates = await like_spread_and_recent_memes(
                user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
            )
        elif r < 0.75:
            candidates = await get_best_memes_from_each_source(
                user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
            )
        else:
            candidates = await less_seen_meme_and_source(
                user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
            )

    if len(candidates) == 0:
        return

    # TODO:
    # inference ML api
    # select the best LIMIT memes -> save them to queue

    await redis.add_memes_to_queue_by_key(queue_key, candidates)
