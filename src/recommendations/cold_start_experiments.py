"""A/B: fresh (<30d) quality memes for true-new cold start (H10)."""

from __future__ import annotations

import hashlib
from typing import Any

from src.tgbot.service import (
    assign_experiment,
    get_experiment_assignment,
    get_experiment_variant,
)

COLD_START_FRESH_VIRAL_EXPERIMENT_ID = "cold_start_fresh_viral_v1"
COLD_START_FRESH_VIRAL_CONTROL = "control"
COLD_START_FRESH_VIRAL_TREATMENT = "treatment_fresh_30d"
COLD_START_FRESH_MAX_AGE_DAYS = 30
COLD_START_FRESH_ENROLL_MAX_MEMES_SENT = 6


def cold_start_fresh_variant_for_user(user_id: int) -> str:
    key = f"{COLD_START_FRESH_VIRAL_EXPERIMENT_ID}:{user_id}"
    bucket = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big") % 2
    if bucket == 0:
        return COLD_START_FRESH_VIRAL_CONTROL
    return COLD_START_FRESH_VIRAL_TREATMENT


def is_cold_start_fresh_eligible(
    nmemes_sent: int,
    nsessions: int,
    cold_start_account_too_old: bool,
) -> bool:
    return (
        nmemes_sent < COLD_START_FRESH_ENROLL_MAX_MEMES_SENT
        and (nsessions or 0) <= 1
        and not cold_start_account_too_old
    )


def build_cold_start_fresh_assignment(user_id: int) -> tuple[str, dict[str, Any]]:
    variant = cold_start_fresh_variant_for_user(user_id)
    return variant, {
        "assignment_strategy": "sha256(experiment_id:user_id)%2",
        "max_age_days": COLD_START_FRESH_MAX_AGE_DAYS,
        "primary_read": (
            "first-tap %, first-like %, reached-5; k-factor: non-self share clicks, invites"
        ),
    }


async def get_or_assign_cold_start_fresh_variant(
    user_id: int,
    *,
    nmemes_sent: int,
    nsessions: int,
    cold_start_account_too_old: bool,
) -> str:
    assignment = await get_experiment_assignment(
        user_id,
        COLD_START_FRESH_VIRAL_EXPERIMENT_ID,
    )
    if assignment is not None:
        return assignment["variant"]

    if not is_cold_start_fresh_eligible(nmemes_sent, nsessions, cold_start_account_too_old):
        return COLD_START_FRESH_VIRAL_CONTROL

    proposed_variant, assignment_metadata = build_cold_start_fresh_assignment(user_id)
    inserted = await assign_experiment(
        user_id,
        COLD_START_FRESH_VIRAL_EXPERIMENT_ID,
        proposed_variant,
        assignment_metadata,
    )
    if inserted:
        return proposed_variant

    return (
        await get_experiment_variant(user_id, COLD_START_FRESH_VIRAL_EXPERIMENT_ID)
        or COLD_START_FRESH_VIRAL_CONTROL
    )


def fresh_max_age_days_for_variant(
    variant: str,
    *,
    nmemes_sent: int,
    nsessions: int,
    cold_start_account_too_old: bool,
) -> int | None:
    if variant != COLD_START_FRESH_VIRAL_TREATMENT:
        return None
    if not is_cold_start_fresh_eligible(nmemes_sent, nsessions, cold_start_account_too_old):
        return None
    return COLD_START_FRESH_MAX_AGE_DAYS
