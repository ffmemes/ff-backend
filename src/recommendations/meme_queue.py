import logging
import uuid
from math import ceil
from typing import Any, Optional

from sqlalchemy import text

from src import redis
from src.database import fetch_all
from src.recommendations.blender import blend
from src.recommendations.candidates import (
    CandidatesRetriever,
)
from src.recommendations.utils import exclude_meme_ids_sql_filter
from src.storage.schemas import MemeData
from src.tgbot.constants import UserType
from src.tgbot.service import assign_experiment, get_experiment_variant
from src.tgbot.user_info import get_user_info

RECENTLY_LIKED_BLENDER_EXPERIMENT_ID = "recently_liked_blender_mature_v1"
RECENTLY_LIKED_BLENDER_CONTROL = "control"
RECENTLY_LIKED_BLENDER_TREATMENT = "treatment"

MATURE_BLENDER_CONTROL_WEIGHTS = {
    "best_uploaded_memes": 0.3,
    "like_spread_and_recent_memes": 0.3,
    "lr_smoothed": 0.4,
    "recently_liked": 0.2,
    "goat": 0.1,
    "es_ranked": 0.1,
}
MATURE_BLENDER_TREATMENT_WEIGHTS = {
    "best_uploaded_memes": 0.3,
    "like_spread_and_recent_memes": 0.25,
    "lr_smoothed": 0.35,
    "recently_liked": 0.3,
    "goat": 0.1,
    "es_ranked": 0.1,
}


async def get_or_assign_recently_liked_blender_variant(user_id: int) -> str:
    variant = await get_experiment_variant(user_id, RECENTLY_LIKED_BLENDER_EXPERIMENT_ID)
    if variant is not None:
        return variant

    proposed = (
        RECENTLY_LIKED_BLENDER_TREATMENT if user_id % 2 == 0 else RECENTLY_LIKED_BLENDER_CONTROL
    )
    inserted = await assign_experiment(
        user_id,
        RECENTLY_LIKED_BLENDER_EXPERIMENT_ID,
        proposed,
    )
    if inserted:
        return proposed

    return (
        await get_experiment_variant(user_id, RECENTLY_LIKED_BLENDER_EXPERIMENT_ID)
        or RECENTLY_LIKED_BLENDER_CONTROL
    )


async def get_recently_liked_blender_weights(user_id: int) -> dict[str, float]:
    try:
        variant = await get_or_assign_recently_liked_blender_variant(user_id)
    except Exception:
        logging.warning(
            "recently_liked blender assignment failed for user %d",
            user_id,
            exc_info=True,
        )
        return dict(MATURE_BLENDER_CONTROL_WEIGHTS)

    if variant == RECENTLY_LIKED_BLENDER_TREATMENT:
        return dict(MATURE_BLENDER_TREATMENT_WEIGHTS)

    return dict(MATURE_BLENDER_CONTROL_WEIGHTS)


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


async def check_queue(user_id: int) -> bool:
    """Refill queue if low. Returns True if lock was acquired (work done or skipped).

    Uses a tokenized Redis lock to prevent concurrent generation for the
    same user. Without this, fast users trigger multiple fire-and-forget
    tasks that read the same queue snapshot, generate identical candidates,
    and add duplicates to the Redis list.
    """
    lock_key = f"meme_queue_lock:{user_id}"
    token = str(uuid.uuid4())
    acquired = await redis.redis_client.set(lock_key, token, nx=True, ex=30)
    if not acquired:
        return False

    try:
        queue_key = redis.get_meme_queue_key(user_id)
        queue_length = await redis.get_meme_queue_length_by_key(queue_key)

        if queue_length <= 8:
            await generate_recommendations(user_id, limit=15)
    except Exception:
        # DB connection errors (pool exhaustion, connection killed mid-query)
        # are expected under traffic spikes. Queue will refill on next attempt.
        logging.warning("check_queue failed for user %d", user_id, exc_info=True)
    finally:
        # Only release if we still own the lock (token match).
        # If TTL expired and another task acquired it, don't delete theirs.
        current = await redis.redis_client.get(lock_key)
        if current == token:
            await redis.redis_client.delete(lock_key)

    return True


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
                ON R.user_id = :user_id
                AND R.meme_id = M.id
            INNER JOIN user_language UL
                ON UL.user_id = :user_id
                AND UL.language_code = M.language_code
            WHERE 1=1
                AND M.status = 'ok'
                AND R.meme_id IS NULL
                {exclude_meme_ids_sql_filter(exclude_ids)}
            ORDER BY COALESCE(MS.nmemes_sent, 0), M.id
            LIMIT :limit
        """
        params: dict = {"user_id": user_id, "limit": limit}
        if exclude_ids:
            params["exclude_meme_ids"] = exclude_ids

        return await fetch_all(text(query), params)

    async def get_candidates(user_id, limit):
        """Route to the right engine mix based on user maturity.

        Cold start (<30 memes) uses 3-phase adaptive approach:
          Phase 1 (0-5):  Quality-first — top-liked memes with social proof
                          (>=20 reactions, lr_smoothed >= 0.10)
          Phase 2 (6-15): Adapt — weight sources by user's raw reactions
          Phase 3 (16-30): Transition — blend adapt + growing engines

        Fallback chain: phase engine -> lr_smoothed -> best_uploaded_memes
        """

        # Cold start: 3-phase adaptive
        if nmemes_sent < 30:
            if nmemes_sent < 6:
                # Phase 1: diverse exploration from top sources
                engine = "cold_start_explore"
            elif nmemes_sent < 16:
                # Phase 2: adapt to user's reactions in real-time
                engine = "cold_start_adapt"
            else:
                # Phase 3: transition — blend adapt with growing engines
                weights = {
                    "cold_start_adapt": 0.5,
                    "lr_smoothed": 0.3,
                    "like_spread_and_recent_memes": 0.2,
                }
                candidates_dict = await retriever.get_candidates_dict(
                    weights.keys(), user_id, limit, exclude_mem_ids=meme_ids_in_queue
                )
                fixed_pos = {0: "cold_start_adapt"}
                blended = blend(candidates_dict, weights, fixed_pos, limit, random_seed)
                if blended:
                    return blended
                # fallback if blend is empty
                engine = "cold_start_adapt"

            candidates = await retriever.get_candidates(
                engine, user_id, limit, exclude_mem_ids=meme_ids_in_queue
            )

            # Fallback chain: -> lr_smoothed -> best_uploaded_memes
            if len(candidates) == 0:
                logging.info(
                    "Cold start %s empty for user %s, falling back to lr_smoothed",
                    engine,
                    user_id,
                )
                candidates = await retriever.get_candidates(
                    "lr_smoothed",
                    user_id,
                    limit,
                    exclude_mem_ids=meme_ids_in_queue,
                    min_sends=10,
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
                "goat": 0.1,
                "es_ranked": 0.1,
                "like_spread_and_recent_memes": 0.2,
            }

            candidates_dict = await retriever.get_candidates_dict(
                weights.keys(), user_id, limit, exclude_mem_ids=meme_ids_in_queue
            )

            fixed_pos = {0: "lr_smoothed"}
            return blend(candidates_dict, weights, fixed_pos, limit, random_seed)

        # >=100
        weights = await get_recently_liked_blender_weights(user_id)

        candidates_dict = await retriever.get_candidates_dict(
            weights.keys(), user_id, limit, exclude_mem_ids=meme_ids_in_queue
        )

        fixed_pos = {0: "lr_smoothed"}
        candidates = blend(candidates_dict, weights, fixed_pos, limit, random_seed)

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

        # Last resort: if both pools are empty, fetch ANY unseen meme
        if len(candidates) == 0:
            exclude_ids = meme_ids_in_queue
            fallback_query = f"""
                SELECT
                    M.id,
                    M.type,
                    M.telegram_file_id,
                    M.caption,
                    'last_resort' AS recommended_by
                FROM meme M
                LEFT JOIN user_meme_reaction R
                    ON R.user_id = :user_id
                    AND R.meme_id = M.id
                INNER JOIN user_language UL
                    ON UL.user_id = :user_id
                    AND UL.language_code = M.language_code
                WHERE M.status = 'ok'
                    AND R.meme_id IS NULL
                    {exclude_meme_ids_sql_filter(exclude_ids)}
                ORDER BY M.id DESC
                LIMIT :limit
            """
            params: dict = {"user_id": user_id, "limit": limit}
            if exclude_ids:
                params["exclude_meme_ids"] = exclude_ids
            candidates = await fetch_all(text(fallback_query), params)
            if candidates:
                logging.info(
                    "Moderator user %s: low_sent + blender empty, last_resort found %d memes",
                    user_id,
                    len(candidates),
                )
    else:
        candidates = await get_candidates(user_id, limit)

    if len(candidates) > 0:
        await redis.add_memes_to_queue_by_key(queue_key, candidates)

    return candidates
