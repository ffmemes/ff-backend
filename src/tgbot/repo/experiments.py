from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from src.database import execute, experiment_assignment, fetch_one


async def get_experiment_assignment(user_id: int, experiment_id: str) -> dict[str, Any] | None:
    """Get a user's experiment assignment row. Returns None if not assigned."""
    query = select(
        experiment_assignment.c.variant,
        experiment_assignment.c.assignment_metadata,
        experiment_assignment.c.assigned_at,
    ).where(
        experiment_assignment.c.experiment_id == experiment_id,
        experiment_assignment.c.user_id == user_id,
    )
    return await fetch_one(query)


async def get_experiment_variant(user_id: int, experiment_id: str) -> str | None:
    """Get a user's experiment variant. Returns None if not assigned."""
    row = await get_experiment_assignment(user_id, experiment_id)
    return row["variant"] if row else None


async def assign_experiment(
    user_id: int,
    experiment_id: str,
    variant: str,
    assignment_metadata: dict[str, Any] | None = None,
) -> bool:
    """Assign a user to an experiment variant. Idempotent (ON CONFLICT DO NOTHING).

    Returns True when this call inserted a new assignment row, False when a
    row already existed. Callers can use the return value as a once-per-user
    gate (e.g. emitting `evaluated` exactly once when the cohort is decided).
    """
    insert_query = (
        insert(experiment_assignment)
        .values(
            experiment_id=experiment_id,
            user_id=user_id,
            variant=variant,
            assignment_metadata=assignment_metadata or {},
        )
        .on_conflict_do_nothing(
            index_elements=["experiment_id", "user_id"],
        )
    )
    result = await execute(insert_query)
    return result.rowcount > 0
