import hashlib
import logging
from typing import Any

from src.flows.events import safe_emit
from src.tgbot.service import assign_experiment, get_experiment_variant

logger = logging.getLogger(__name__)

MEME_LIKE_COUNT_EXPERIMENT_ID = "meme_like_count"
MEME_LIKE_COUNT_CONTROL = "control"
MEME_LIKE_COUNT_TREATMENT = "treatment"
MEME_LIKE_COUNT_MIN_VISIBLE_LIKES = 5
MEME_LIKE_COUNT_SAMPLE_GATE_PER_VARIANT = 1000


def _variant_for_user(user_id: int) -> str:
    key = f"{MEME_LIKE_COUNT_EXPERIMENT_ID}:{user_id}"
    bucket = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big") % 2
    if bucket == 0:
        return MEME_LIKE_COUNT_CONTROL
    return MEME_LIKE_COUNT_TREATMENT


def build_meme_like_count_assignment(user_id: int) -> tuple[str, dict[str, Any]]:
    variant = _variant_for_user(user_id)
    return variant, {
        "assignment_strategy": "sha256(experiment_id:user_id)%2",
        "min_visible_likes": MEME_LIKE_COUNT_MIN_VISIBLE_LIKES,
        "shows_dislikes": False,
        "button_format": "heart_count_when_like_count_reaches_threshold",
        "sample_gate_per_variant": MEME_LIKE_COUNT_SAMPLE_GATE_PER_VARIANT,
    }


async def get_or_assign_meme_like_count_variant(user_id: int) -> str:
    variant = await get_experiment_variant(user_id, MEME_LIKE_COUNT_EXPERIMENT_ID)
    if variant is not None:
        return variant

    proposed, metadata = build_meme_like_count_assignment(user_id)
    inserted = await assign_experiment(
        user_id,
        MEME_LIKE_COUNT_EXPERIMENT_ID,
        proposed,
        metadata,
    )
    if inserted:
        safe_emit(
            f"ff.experiment.{MEME_LIKE_COUNT_EXPERIMENT_ID}.evaluated",
            f"user.{user_id}",
            {
                "user_id": user_id,
                "group": proposed,
                "min_visible_likes": MEME_LIKE_COUNT_MIN_VISIBLE_LIKES,
            },
        )
        return proposed

    return (
        await get_experiment_variant(user_id, MEME_LIKE_COUNT_EXPERIMENT_ID)
        or MEME_LIKE_COUNT_CONTROL
    )


async def get_visible_meme_like_count(user_id: int, nlikes: int | None) -> int | None:
    try:
        variant = await get_or_assign_meme_like_count_variant(user_id)
    except Exception:
        logger.warning(
            "meme like-count experiment assignment failed for user %d",
            user_id,
            exc_info=True,
        )
        return None

    if variant != MEME_LIKE_COUNT_TREATMENT:
        return None

    like_count = int(nlikes or 0)
    if like_count < MEME_LIKE_COUNT_MIN_VISIBLE_LIKES:
        return None
    return like_count
