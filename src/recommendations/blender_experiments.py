import hashlib
import logging

from src.tgbot.service import assign_experiment, get_experiment_assignment

logger = logging.getLogger(__name__)


# --- explore_budget_v1: labeling budget + fresh-viral + idle-return first slot ---
# See experiments/2026-10-30-explore-budget.md.

EXPLORE_BUDGET_V1_EXPERIMENT_ID = "explore_budget_v1"
EXPLORE_BUDGET_V1_CONTROL = "control"
EXPLORE_BUDGET_V1_TREATMENT = "treatment"
EXPLORE_BUDGET_V1_MIN_MEMES_SENT = 30  # cold start keeps its own engines


def explore_budget_v1_variant_for_user(user_id: int) -> str:
    key = f"{EXPLORE_BUDGET_V1_EXPERIMENT_ID}:{user_id}"
    bucket = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big") % 2
    return EXPLORE_BUDGET_V1_CONTROL if bucket == 0 else EXPLORE_BUDGET_V1_TREATMENT


async def is_explore_budget_v1_treatment(user_id: int, nmemes_sent: int) -> bool:
    if nmemes_sent < EXPLORE_BUDGET_V1_MIN_MEMES_SENT:
        return False
    try:
        assignment = await get_experiment_assignment(user_id, EXPLORE_BUDGET_V1_EXPERIMENT_ID)
        if assignment is not None:
            return assignment["variant"] == EXPLORE_BUDGET_V1_TREATMENT
        variant = explore_budget_v1_variant_for_user(user_id)
        await assign_experiment(
            user_id,
            EXPLORE_BUDGET_V1_EXPERIMENT_ID,
            variant,
            {"assignment_strategy": "sha256(experiment_id:user_id)%2"},
        )
    except Exception:
        logger.warning("explore_budget_v1 assignment failed for user %d", user_id, exc_info=True)
        return False
    return variant == EXPLORE_BUDGET_V1_TREATMENT
