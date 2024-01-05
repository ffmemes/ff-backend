import orjson
import asyncio

from src import redis
from src.storage.schemas import MemeData

from src.recommendations.service import (
    get_unseen_memes
)


async def get_next_meme_for_user(user_id: int) -> MemeData | None:
    queue_key = redis.get_meme_queue_key(user_id)
    meme_data = await redis.pop_meme_from_queue_by_key(queue_key)

    asyncio.create_task(check_queue(user_id))    
    if meme_data:
        return MemeData(**meme_data)
    
    return None


async def has_memes_in_queue(user_id: int) -> bool:
    queue_key = redis.get_meme_queue_key(user_id)
    queue_length = await redis.get_meme_queue_length_by_key(queue_key)
    return queue_length > 0


async def check_queue(user_id: int):
    queue_key = redis.get_meme_queue_key(user_id)
    queue_length = await redis.get_meme_queue_length_by_key(queue_key)

    if queue_length <= 3:
        await generate_recommendations(user_id)


async def generate_recommendations(user_id, limit=10):
    queue_key = redis.get_meme_queue_key(user_id)
    memes_in_queue_data = await redis.get_all_memes_in_queue_by_key(queue_key)
    memes_in_queue = [orjson.loads(meme) for meme in memes_in_queue_data]
    meme_ids_in_queue = [meme["id"] for meme in memes_in_queue]
    # TODO: exclude these ids

    candidates = await get_unseen_memes(
        user_id, 
        limit=limit, 
        exclude_meme_ids=meme_ids_in_queue
    )

    await redis.add_memes_to_queue_by_key(queue_key, candidates)

    # inference ML api 
    # select the best LIMIT memes -> save them to queue
    pass