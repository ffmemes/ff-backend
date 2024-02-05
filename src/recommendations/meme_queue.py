from src import redis
from src.recommendations.candidates import sorted_by_user_source_lr_meme_lr_meme_age
from src.recommendations.cold_start import get_best_memes_from_each_source
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


async def check_queue(user_id: int):
    queue_key = redis.get_meme_queue_key(user_id)
    queue_length = await redis.get_meme_queue_length_by_key(queue_key)

    if queue_length <= 4:
        await generate_recommendations(user_id, limit=10)


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


async def generate_recommendations(user_id, limit=10):
    queue_key = redis.get_meme_queue_key(user_id)
    memes_in_queue = await redis.get_all_memes_in_queue_by_key(queue_key)
    meme_ids_in_queue = [meme["id"] for meme in memes_in_queue]

    candidates = await sorted_by_user_source_lr_meme_lr_meme_age(
        user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
    )
    if len(candidates) == 0:
        return

    await redis.add_memes_to_queue_by_key(queue_key, candidates)

    # inference ML api
    # select the best LIMIT memes -> save them to queue
    pass
