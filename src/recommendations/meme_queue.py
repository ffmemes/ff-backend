import logging
import uuid
from typing import Any, Optional

from sqlalchemy import text

from src import redis
from src.config import settings
from src.database import fetch_all, fetch_one
from src.recommendations.blender import blend
from src.recommendations.blender_experiments import (
    MATURE_BLENDER_CONTROL_WEIGHTS,
    get_recently_liked_blender_v2_weights,
    get_text_light_blender_v1_weights,
)
from src.recommendations.candidates import (
    CandidatesRetriever,
)
from src.recommendations.pipeline import (
    RecommendationBatchPipeline,
    RecommendationBatchRequest,
    record_recommendation_batch_diagnostics,
)
from src.storage.schemas import MemeData
from src.tgbot.constants import UserType
from src.tgbot.user_info import get_user_info


async def get_next_meme_for_user(user_id: int) -> MemeData | None:
    queue_key = redis.get_meme_queue_key(user_id)

    while True:
        meme_data = await redis.pop_meme_from_queue_by_key(queue_key)
        if not meme_data:
            return None

        if await _queued_meme_is_sendable(user_id, int(meme_data["id"])):
            return MemeData(**meme_data)

        logging.info(
            "Dropped stale queued meme %s for user %s before send",
            meme_data.get("id"),
            user_id,
        )


async def _queued_meme_is_sendable(user_id: int, meme_id: int) -> bool:
    row = await fetch_one(
        text(
            """
            SELECT M.id
            FROM meme M
            LEFT JOIN user_meme_reaction R
                ON R.meme_id = M.id
                AND R.user_id = :user_id
            WHERE M.id = :meme_id
                AND M.status = 'ok'
                AND R.meme_id IS NULL
        """
        ),
        {"user_id": user_id, "meme_id": meme_id},
    )
    return row is not None


async def has_memes_in_queue(user_id: int) -> bool:
    queue_key = redis.get_meme_queue_key(user_id)
    queue_length = await redis.get_meme_queue_length_by_key(queue_key)
    return queue_length > 0


async def clear_meme_queue_for_user(user_id: int) -> None:
    queue_key = redis.get_meme_queue_key(user_id)
    await redis.delete_by_key(queue_key)


def _trim_error_message(value: str, limit: int = 300) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


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
    user_info = await get_user_info(user_id)
    if nmemes_sent is None:
        nmemes_sent = user_info["nmemes_sent"]

    # FFM-1161: nsessions gate. cold_start engines were designed for first-session
    # users; the cached user_info may predate the gate (1h TTL) — treat missing as 0
    # so we don't accidentally route dormant returners into cold_start.
    nsessions = user_info.get("nsessions") or 0

    queue_key = redis.get_meme_queue_key(user_id)

    memes_in_queue = await redis.get_all_memes_in_queue_by_key(queue_key)
    meme_ids_in_queue = [meme["id"] for meme in memes_in_queue]

    if retriever is None:
        retriever = CandidatesRetriever()

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

    pipeline = RecommendationBatchPipeline(
        retriever=retriever,
        blend_func=blend,
        fetch_all_func=fetch_all,
        mature_weights_func=get_recently_liked_blender_v2_weights,
        text_light_weights_func=get_text_light_blender_v1_weights,
        mature_control_weights=MATURE_BLENDER_CONTROL_WEIGHTS,
    )
    result = await pipeline.run(
        RecommendationBatchRequest(
            user_id=user_id,
            limit=limit,
            nmemes_sent=nmemes_sent,
            nsessions=nsessions,
            user_type=None if user_type is None else user_type.value,
            meme_ids_in_queue=meme_ids_in_queue,
            random_seed=random_seed,
            cold_start_nsessions_gate_enabled=settings.COLD_START_NSESSIONS_GATE_ENABLED,
            # FFM-1357: stop new exposure until this overlay has a CEO-owned
            # active experiment record. Existing assignment rows remain readable.
            text_light_blender_v1_enabled=False,
            source_diversity_enabled=settings.RECOMMENDATION_SOURCE_DIVERSITY_ENABLED,
            shadow_scoring_enabled=settings.RECOMMENDATION_SHADOW_SCORING_ENABLED,
            diagnostics_sample_rate=settings.RECOMMENDATION_DIAGNOSTICS_SAMPLE_RATE,
        )
    )
    candidates = result.selected

    try:
        if len(candidates) > 0:
            await redis.add_memes_to_queue_by_key(queue_key, candidates)
            result.diagnostics.enqueued_count = len(candidates)
    except Exception as error:
        result.diagnostics.outcome = "enqueue_failure"
        result.diagnostics.error_type = type(error).__name__
        result.diagnostics.error_message = _trim_error_message(str(error))
        record_recommendation_batch_diagnostics(result.diagnostics, force_full=True)
        raise

    record_recommendation_batch_diagnostics(result.diagnostics)
    return candidates
