"""Safe Prefect event emission for flows.

Wraps emit_event in try-except so a Prefect API hiccup
never crashes the flow itself (critical gap from eng review).
"""

import logging

logger = logging.getLogger(__name__)


def safe_emit(event: str, resource_id: str, payload: dict | None = None) -> None:
    """Emit a Prefect event, silently catching errors."""
    try:
        from prefect.events import emit_event

        emit_event(
            event=event,
            resource={"prefect.resource.id": resource_id},
            payload=payload or {},
        )
    except Exception as e:
        logger.warning("Failed to emit event %s: %s", event, e)
