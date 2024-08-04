import random

from src import redis
from src.recommendations.candidates import (
    get_best_memes_from_each_source,
    get_fast_dopamine,
    get_lr_smoothed,
    get_selected_sources,
    less_seen_meme_and_source,
    like_spread_and_recent_memes,
    uploaded_memes,
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

    candidates = []

    candidates = await get_selected_sources(
        user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
    )

    if len(candidates) == 0:
        candidates = await get_best_memes_from_each_source(
            user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
        )

    if len(candidates) == 0:
        candidates = await get_lr_smoothed(
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

    candidates = []

    r = random.random()

    if r < 0.3:
        candidates = await get_best_memes_from_each_source(
            user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
        )

    elif user_info["nmemes_sent"] < 30:
        candidates = await get_selected_sources(
            user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
        )

        if len(candidates) == 0:
            candidates = await get_best_memes_from_each_source(
                user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
            )

    elif user_info["nmemes_sent"] < 100:
        if r < 0.2:
            candidates = await uploaded_memes(
                user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
            )
        elif r < 0.4:
            candidates = await get_fast_dopamine(
                user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
            )
        elif r < 0.6:
            candidates = await get_best_memes_from_each_source(
                user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
            )
        else:
            candidates = await get_lr_smoothed(
                user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
            )

    else:
        if r < 0.3:
            candidates = await uploaded_memes(
                user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
            )
        if r < 0.6:
            candidates = await like_spread_and_recent_memes(
                user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
            )
        else:
            candidates = await get_lr_smoothed(
                user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
            )

    if len(candidates) == 0:
        candidates = await get_lr_smoothed(
            user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
        )

    if len(candidates) == 0 and user_info["nmemes_sent"] > 1000:
        candidates = await less_seen_meme_and_source(
            user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
        )

    if len(candidates) == 0:
        # TODO: fallback to some algo which will always return something
        return

    # TODO:
    # inference ML api
    # select the best LIMIT memes -> save them to queue

    await redis.add_memes_to_queue_by_key(queue_key, candidates)
