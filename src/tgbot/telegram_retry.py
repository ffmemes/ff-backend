from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from telegram.error import NetworkError, TimedOut

logger = logging.getLogger(__name__)

T = TypeVar("T")
TRANSIENT_TELEGRAM_ERRORS = (NetworkError, TimedOut)


async def telegram_call_with_retry(
    call: Callable[[], Awaitable[T]],
    *,
    action: str,
    attempts: int = 2,
    initial_delay: float = 0.3,
) -> T:
    """Run one Telegram Bot API call with a tiny retry for transport failures."""
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    delay = initial_delay
    for attempt in range(1, attempts + 1):
        try:
            return await call()
        except TRANSIENT_TELEGRAM_ERRORS as error:
            if attempt == attempts:
                logger.warning(
                    "Telegram %s failed after %s attempts: %s",
                    action,
                    attempts,
                    error,
                )
                raise
            logger.warning(
                "Transient Telegram %s failure on attempt %s/%s: %s",
                action,
                attempt,
                attempts,
                error,
            )
            await asyncio.sleep(delay)
            delay *= 2

    raise RuntimeError("unreachable")
