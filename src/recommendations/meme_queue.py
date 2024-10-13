from typing import Any, Optional

from src import redis
from src.recommendations.blender import blend
from src.recommendations.candidates import (
    CandidatesRetriever,
    get_best_memes_from_each_source,
    get_fast_dopamine,
    get_lr_smoothed,
    get_selected_sources,
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

    if len(candidates) == 0:
        candidates = await get_fast_dopamine(
            user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
        )

    if len(candidates) == 0:
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


async def generate_recommendations(
    user_id: int,
    limit: int,
    nmemes_sent: Optional[int] = None,
    retriever: Optional[CandidatesRetriever] = None,
    random_seed: int = 42,
) -> list[dict[str, Any]]:
    """Uses blender to mix candidates from different engines

    The function aims to keep the same logic as generate_candidates but
    with blending.

    Will be refactored
    """

    if nmemes_sent is None:
        user_info = await get_user_info(user_id)
        nmemes_sent = user_info["nmemes_sent"]

    queue_key = redis.get_meme_queue_key(user_id)

    meme_ids_in_queue = []
    memes_in_queue = await redis.get_all_memes_in_queue_by_key(queue_key)
    meme_ids_in_queue = [meme["id"] for meme in memes_in_queue]

    if retriever is None:
        retriever = CandidatesRetriever()

    async def get_candidates(user_id, limit):
        """A helper function to avoid copy-paste"""

        # <30 is treated as cold start. no blending
        if nmemes_sent < 30:
            candidates = await retriever.get_candidates(
                "fast_dopamine", user_id, limit, exclude_mem_ids=meme_ids_in_queue
            )

            if len(candidates) == 0:
                candidates = await retriever.get_candidates(
                    "best_memes_from_each_source",
                    user_id,
                    limit,
                    exclude_mem_ids=meme_ids_in_queue,
                )

            return candidates

        if nmemes_sent < 100:
            weights = {
                "uploaded_memes": 0.2,
                "fast_dopamine": 0.2,
                "best_memes_from_each_source": 0.2,
                "lr_smoothed": 0.2,
                "recently_liked": 0.2,
            }

            candidates_dict = await retriever.get_candidates_dict(
                weights.keys(), user_id, limit, exclude_mem_ids=meme_ids_in_queue
            )

            fixed_pos = {0: "lr_smoothed"}
            return blend(candidates_dict, weights, fixed_pos, limit, random_seed)

        # >=100
        weights = {
            "uploaded_memes": 0.3,
            "like_spread_and_recent_memes": 0.3,
            "lr_smoothed": 0.4,
        }

        candidates_dict = await retriever.get_candidates_dict(
            weights.keys(), user_id, limit, exclude_mem_ids=meme_ids_in_queue
        )

        fixed_pos = {0: "lr_smoothed"}
        candidates = blend(candidates_dict, weights, fixed_pos, limit, random_seed)

        if len(candidates) == 0 and nmemes_sent > 1000:
            candidates = await retriever.get_candidates(
                "less_seen_meme_and_source",
                user_id,
                limit,
                exclude_mem_ids=meme_ids_in_queue,
            )

        if len(candidates) == 0:
            candidates = await retriever.get_candidates(
                "best_memes_from_each_source",
                user_id,
                limit,
                exclude_mem_ids=meme_ids_in_queue,
            )

        return candidates

    candidates = await get_candidates(user_id, limit)
    if len(candidates) > 0:
        await redis.add_memes_to_queue_by_key(queue_key, candidates)

    return candidates
