"""
Shared Prefect flow hooks for failure notifications.
"""

import logging
import traceback

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


def _extract_error_msg(state) -> str:
    """Extract error message from a Prefect flow run state."""
    if state.message:
        return state.message[:500]
    if state.result:
        try:
            exc = state.result(raise_on_failure=False)
            if isinstance(exc, BaseException):
                tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
                return "".join(tb)[-500:]
        except Exception:
            return str(state.result)[:500]
    return ""


def notify_telegram_on_failure(flow, flow_run, state):
    """Send failure alerts to Telegram and Paperclip QA when a flow fails."""
    error_msg = _extract_error_msg(state)

    # Notify Paperclip QA (independent of Telegram config)
    try:
        from src.integrations.paperclip import notify_qa_sync

        notify_qa_sync(flow.name, flow_run.name, error_msg)
    except Exception as e:
        logger.error("Failed to notify Paperclip QA: %s", e)

    # Notify Telegram admin chat
    bot_token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.ADMIN_LOGS_CHAT_ID

    if not bot_token or not chat_id:
        logger.warning(
            "Cannot send failure alert: TELEGRAM_BOT_TOKEN or ADMIN_LOGS_CHAT_ID not set"
        )
        return

    text = f"Flow FAILED: {flow.name}\nRun: {flow_run.name}\nError: {error_msg}"

    try:
        httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except Exception as e:
        logger.error("Failed to send Telegram failure alert: %s", e)
