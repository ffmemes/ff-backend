import logging
from math import ceil
from typing import Any, Optional

from sqlalchemy import text

from src import redis
from src.database import fetch_all
from src.recommendations.blender import blend
from src.recommendations.candidates import (
    CandidatesRetriever,
    best_uploaded_memes,
    get_lr_smoothed,
    get_selected_sources,
)
from src.recommendations.utils import exclude_meme_ids_sql_filter
from src.storage.schemas import MemeData
from src.tgbot.constants import UserType
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

    candidates = await get_lr_smoothed(
        user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
    )

    if len(candidates) == 0:
        candidates = await best_uploaded_memes(
            user_id, limit=limit, exclude_meme_ids=meme_ids_in_queue
        )

    if len(candidates) == 0:
        candidates = await get_selected_sources(
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
    random_seed: int | None = None,
) -> list[dict[str, Any]]:
    """Uses blender to mix candidates from different engines

    The function aims to keep the same logic as generate_candidates but
    with blending.

    Will be refactored
    """

    user_info = await get_user_info(user_id)
    if nmemes_sent is None:
        nmemes_sent = user_info["nmemes_sent"]

    queue_key = redis.get_meme_queue_key(user_id)

    meme_ids_in_queue = []
    memes_in_queue = await redis.get_all_memes_in_queue_by_key(queue_key)
    meme_ids_in_queue = [meme["id"] for meme in memes_in_queue]

    if retriever is None:
        retriever = CandidatesRetriever()

    async def get_low_sent_candidates(
        user_id: int, limit: int, exclude_ids: list[int]
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []

        query = f"""
            SELECT
                M.id,
                M.type,
                M.telegram_file_id,
                M.caption,
                'low_sent_pool' AS recommended_by
            FROM meme M
            LEFT JOIN meme_stats MS
                ON MS.meme_id = M.id
            LEFT JOIN user_meme_reaction R
                ON R.user_id = {user_id}
                AND R.meme_id = M.id
            INNER JOIN user_language UL
                ON UL.user_id = {user_id}
                AND UL.language_code = M.language_code
            WHERE 1=1
                AND M.status = 'ok'
                AND R.meme_id IS NULL
                {exclude_meme_ids_sql_filter(exclude_ids)}
            ORDER BY COALESCE(MS.nmemes_sent, 0), M.id
            LIMIT {limit}
        """

        return await fetch_all(text(query))

    async def get_candidates(user_id, limit):
        """A helper function to avoid copy-paste"""

        # <30 is treated as cold start. no blending
        if nmemes_sent < 30:
            candidates = await retriever.get_candidates(
                "lr_smoothed",
                user_id,
                limit,
                exclude_mem_ids=meme_ids_in_queue,
            )

            if len(candidates) == 0:
                candidates = await retriever.get_candidates(
                    "best_uploaded_memes", user_id, limit, exclude_mem_ids=meme_ids_in_queue
                )

            return candidates

        if nmemes_sent < 100:
            weights = {
                "best_uploaded_memes": 0.1,
                "lr_smoothed": 0.3,
                "recently_liked": 0.2,
                "goat": 0.2,
                "like_spread_and_recent_memes": 0.2,
            }

            candidates_dict = await retriever.get_candidates_dict(
                weights.keys(), user_id, limit, exclude_mem_ids=meme_ids_in_queue
            )

            fixed_pos = {0: "lr_smoothed"}
            return blend(candidates_dict, weights, fixed_pos, limit, random_seed)

        # >=100
        weights = {
            "best_uploaded_memes": 0.3,
            "like_spread_and_recent_memes": 0.3,
            "lr_smoothed": 0.4,
            "recently_liked": 0.2,
            "goat": 0.2,
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

        return candidates

    user_type_value = user_info.get("type")
    user_type = None
    if user_type_value:
        try:
            user_type = UserType(str(user_type_value))
        except ValueError:
            logging.warning(
                "Unknown user type '%s' for user_id=%s during queue generation",
                user_type_value,
                user_id,
            )

    candidates: list[dict[str, Any]] = []

    if user_type in (UserType.MODERATOR, UserType.ADMIN):
        low_sent_quota = ceil(limit * 0.75)
        low_sent_candidates = await get_low_sent_candidates(
            user_id,
            low_sent_quota,
            meme_ids_in_queue,
        )
        candidates.extend(low_sent_candidates)
        meme_ids_in_queue.extend(candidate["id"] for candidate in low_sent_candidates)

        remaining_limit = max(0, limit - len(candidates))
        if remaining_limit > 0:
            extra_candidates = await get_candidates(user_id, remaining_limit)
            candidates.extend(extra_candidates)
    else:
        candidates = await get_candidates(user_id, limit)

    if len(candidates) > 0:
        await redis.add_memes_to_queue_by_key(queue_key, candidates)

    return candidates
