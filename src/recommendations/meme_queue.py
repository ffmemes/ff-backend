from src import redis
from src.storage.schemas import MemeData

from src.recommendations.candidates import sorted_by_user_source_lr_meme_lr_meme_age
from src.recommendations.cold_start import get_best_memes_from_each_source

from src.recommendations.service import get_user_reactions

from src.tgbot import logs

async def get_next_meme_for_user(user_id: int) -> MemeData | None:
    queue_key = redis.get_meme_queue_key(user_id)
    meme_data = await redis.pop_meme_from_queue_by_key(queue_key)

    if not meme_data:
        return None
    
    # debug
    reactions = await get_user_reactions(user_id)
    received_meme_ids = set(int(r["meme_id"]) for r in reactions)

    if int(meme_data["id"]) in received_meme_ids:
        await logs.log(f"user_id={user_id} will receive meme_id={meme_data['id']} again!")

    queued_memes = await redis.get_all_memes_in_queue_by_key(queue_key)
    queued_meme_ids = set(int(meme["id"]) for meme in queued_memes)

    if queued_meme_ids & received_meme_ids:
        await logs.log(f"user_id={user_id} has received memes in queue: {queued_meme_ids & received_meme_ids}!")

    return MemeData(**meme_data)


async def has_memes_in_queue(user_id: int) -> bool:
    queue_key = redis.get_meme_queue_key(user_id)
    queue_length = await redis.get_meme_queue_length_by_key(queue_key)
    return queue_length > 0


async def check_queue(user_id: int):
    queue_key = redis.get_meme_queue_key(user_id)
    queue_length = await redis.get_meme_queue_length_by_key(queue_key)

    if queue_length <= 2:
        await generate_recommendations(user_id, limit=4)


async def generate_cold_start_recommendations(user_id, limit=10):
    queue_key = redis.get_meme_queue_key(user_id)
    memes_in_queue = await redis.get_all_memes_in_queue_by_key(queue_key)
    meme_ids_in_queue = [meme["id"] for meme in memes_in_queue]

    candidates = await get_best_memes_from_each_source(
        user_id, 
        limit=limit, 
        exclude_meme_ids=meme_ids_in_queue
    )
    print("candidates: ", [c["id"] for c in candidates])
    if len(candidates) == 0:
        return 
    
    await redis.add_memes_to_queue_by_key(queue_key, candidates)


async def generate_recommendations(user_id, limit=10):
    queue_key = redis.get_meme_queue_key(user_id)
    memes_in_queue = await redis.get_all_memes_in_queue_by_key(queue_key)
    meme_ids_in_queue = [meme["id"] for meme in memes_in_queue]

    candidates = await sorted_by_user_source_lr_meme_lr_meme_age(
        user_id, 
        limit=limit, 
        exclude_meme_ids=meme_ids_in_queue
    )
    if len(candidates) == 0:
        return 
    
    await redis.add_memes_to_queue_by_key(queue_key, candidates)

    # inference ML api 
    # select the best LIMIT memes -> save them to queue
    pass