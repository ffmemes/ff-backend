import random

from src import redis
from src.recommendations.candidates import (
    get_best_memes_from_each_source,
    like_spread_and_recent_memes,
    most_liked,
    multiply_all_scores,
    sorted_by_user_source_lr_meme_lr_meme_age,
)
from src.storage.schemas import MemeData


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

    if queue_length <= 4:
        await generate_recommendations(user_id, limit=10)


async def generate_cold_start_recommendations(user_id, limit=10):
    queue_key = redis.get_meme_queue_key(user_id)
    memes_in_queue = await redis.get_all_memes_in_queue_by_key(queue_key)
    meme_ids_in_queue = [meme["id"] for meme in memes_in_queue]

    candidates = await like_spread_and_recent_memes(
        user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
    )
    if len(candidates) == 0:
        return

    await redis.add_memes_to_queue_by_key(queue_key, candidates)


async def generate_recommendations(user_id, limit=10):
    queue_key = redis.get_meme_queue_key(user_id)
    memes_in_queue = await redis.get_all_memes_in_queue_by_key(queue_key)
    meme_ids_in_queue = [meme["id"] for meme in memes_in_queue]

    # randomly choose the strategy
    # TODO: proper A/B testing by users

    r = random.random()
    if r < 0.2:
        candidates = await sorted_by_user_source_lr_meme_lr_meme_age(
            user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
        )
    elif r < 0.4:
        candidates = await most_liked(
            user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
        )
    elif r < 0.6:
        candidates = await like_spread_and_recent_memes(
            user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
        )
    elif r < 0.8:
        candidates = await get_best_memes_from_each_source(
            user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
        )
    else:
        candidates = await multiply_all_scores(
            user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
        )

    if len(candidates) == 0:
        return

    # TODO:
    # inference ML api
    # select the best LIMIT memes -> save them to queue

    await redis.add_memes_to_queue_by_key(queue_key, candidates)
