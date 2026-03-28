"""
Shared Prefect flow hooks for failure notifications.
"""

import logging
import traceback

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


def notify_telegram_on_failure(flow, flow_run, state):
    """Send a Telegram message to ADMIN_LOGS_CHAT_ID when a flow fails."""
    bot_token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.ADMIN_LOGS_CHAT_ID

    if not bot_token or not chat_id:
        logger.warning(
            "Cannot send failure alert: TELEGRAM_BOT_TOKEN or ADMIN_LOGS_CHAT_ID not set"
        )
        return

    error_msg = ""
    if state.message:
        error_msg = state.message[:500]
    elif state.result:
        try:
            exc = state.result(raise_on_failure=False)
            if isinstance(exc, BaseException):
                tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
                error_msg = "".join(tb)[-500:]
        except Exception:
            error_msg = str(state.result)[:500]

    text = f"Flow FAILED: {flow.name}\n" f"Run: {flow_run.name}\n" f"Error: {error_msg}"

    try:
        httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except Exception as e:
        logger.error("Failed to send Telegram failure alert: %s", e)
