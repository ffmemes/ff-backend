"""Sentry scrubbing and safe-context helpers.

Sentry's default EventScrubber (send_default_pii=False) only filters a fixed key
denylist in request/extra/user/breadcrumb data. It does not touch free-form
strings, scope contexts, Sentry Logs, the webhook request body (Telegram message
text) or the Telegram secret-token header, so those are handled here.
"""

import logging
import re
from contextlib import contextmanager
from enum import Enum
from typing import Any, Iterator

import sentry_sdk

logger = logging.getLogger(__name__)

SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "bot_token",
    "database_url",
    "dsn",
    "hash",
    "openai",
    "openrouter",
    "password",
    "redis_url",
    "secret",
    "session",
    "token",
)
UPDATE_TYPES = (
    "message edited_message callback_query inline_query chosen_inline_result "
    "pre_checkout_query chat_member my_chat_member chat_boost"
).split()
RAW_FILE_ID_KEYS = {"file_id", "telegram_file_id", "raw_file_id"}
MAX_CONTEXT_STRING_LENGTH = 500
MAX_LOG_BODY_LENGTH = 2000
TEXT_SCRUBBERS = (
    # URLs carry bot tokens (api.telegram.org/bot<token>/...) and signed params.
    (re.compile(r"https?://[^\s)>\]]+"), "[Filtered]"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE), "Bearer [Filtered]"),
    (
        re.compile(
            r"(?i)\b(api[_-]?key|authorization|bot[_-]?token|dsn|password|secret|token)"
            r"\s*[:=]\s*([^\s,;]+)"
        ),
        r"\1=[Filtered]",
    ),
    (re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b"), "[Filtered]"),  # bare bot token
    # Telegram file IDs and other opaque tokens.
    (
        re.compile(r"\b(?=[A-Za-z0-9_-]{32,}\b)(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9_-]+\b"),
        "[Filtered]",
    ),
)


def before_send(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any] | None:
    """Strip payloads Sentry's default scrubber keeps: webhook body, frame vars, URLs."""
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)  # raw Telegram update: message text, contacts, names
        if isinstance(request.get("url"), str):
            request["url"] = _scrub_text(request["url"])
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {
                k: "[Filtered]" if _is_sensitive_key(k) else v for k, v in headers.items()
            }

    for exc in (event.get("exception") or {}).get("values") or []:
        if isinstance(exc.get("value"), str):
            exc["value"] = _scrub_text(exc["value"])
        for frame in (exc.get("stacktrace") or {}).get("frames") or []:
            frame.pop("vars", None)

    logentry = event.get("logentry")
    if isinstance(logentry, dict):
        logentry.pop("params", None)
        for key in ("message", "formatted"):
            if isinstance(logentry.get(key), str):
                logentry[key] = _scrub_text(logentry[key])

    for crumb in (event.get("breadcrumbs") or {}).get("values") or []:
        if isinstance(crumb.get("message"), str):
            crumb["message"] = _scrub_text(crumb["message"])
        crumb.pop("data", None)

    return event


def before_send_log(log: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any] | None:
    """Scrub searchable Sentry Logs before they leave the process."""
    attributes = log.get("attributes")
    if isinstance(attributes, dict):
        log["attributes"] = {
            key: "[Filtered]"
            if _is_sensitive_key(key) or key.lower().startswith("sentry.message.parameter.")
            else _scrub_text(value)
            if isinstance(value, str)
            else value
            for key, value in attributes.items()
        }
    if isinstance(log.get("body"), str):
        log["body"] = _scrub_text(log["body"])
    return log


@contextmanager
def telegram_update_scope(update: Any) -> Iterator[None]:
    """Attach Telegram update context to Sentry events produced by one webhook."""
    with sentry_sdk.new_scope() as scope:
        user_id = getattr(getattr(update, "effective_user", None), "id", None)
        if user_id is not None:
            scope.set_user({"id": str(user_id)})

        chat = getattr(update, "effective_chat", None)
        update_type = _telegram_update_type(update)
        callback_route = _callback_route(
            getattr(getattr(update, "callback_query", None), "data", None)
        )

        scope.set_tag("ff.module", "telegram_update")
        scope.set_tag("telegram.update_type", update_type)
        if getattr(chat, "type", None):
            scope.set_tag("telegram.chat_type", chat.type)
        if callback_route:
            scope.set_tag("telegram.callback_route", callback_route)

        scope.set_context(
            "telegram_update",
            _clean_context(
                {
                    "update_id": getattr(update, "update_id", None),
                    "chat_id": getattr(chat, "id", None),
                    "message_id": getattr(
                        getattr(update, "effective_message", None), "message_id", None
                    ),
                }
            ),
        )
        yield


def user_upload_observability_context(
    meme: dict[str, Any],
    meme_upload: dict[str, Any],
) -> dict[str, Any]:
    """Build safe user-upload context without raw Telegram payloads or file IDs."""
    media = meme_upload.get("media") or {}
    forward_origin = meme_upload.get("forward_origin") or {}
    return {
        "meme": _clean_context(
            {
                "id": meme.get("id"),
                "type": meme.get("type"),
                "status": meme.get("status"),
                "language_code": meme.get("language_code"),
                "has_telegram_file_id": bool(meme.get("telegram_file_id")),
            }
        ),
        "user_upload": _clean_context(
            {
                "upload_id": meme_upload.get("id"),
                "user_id": meme_upload.get("user_id"),
                "message_id": meme_upload.get("message_id"),
                "language_code": meme_upload.get("language_code"),
                "forward_origin_type": forward_origin.get("type"),
            }
        ),
        "telegram_media": _clean_context(
            {
                key: media.get(key)
                for key in ("file_size", "mime_type", "duration", "width", "height")
            }
        ),
    }


def capture_handled_issue(
    message: str,
    *,
    level: str = "warning",
    user_id: int | str | None = None,
    tags: dict[str, Any] | None = None,
    contexts: dict[str, Any] | None = None,
    error: BaseException | None = None,
) -> str | None:
    """Capture a handled backend failure as a Sentry event with safe context."""
    if error is not None:
        contexts = {
            **(contexts or {}),
            "error": {"type": type(error).__name__, "message": _scrub_text(str(error))},
        }
    return _capture(
        level, user_id, tags, contexts, lambda scope: scope.capture_message(message, level=level)
    )


def capture_handled_exception(
    message: str,
    error: BaseException,
    *,
    level: str = "error",
    user_id: int | str | None = None,
    tags: dict[str, Any] | None = None,
    contexts: dict[str, Any] | None = None,
) -> str | None:
    """Capture a handled exception with stack trace and safe context."""
    contexts = {
        **(contexts or {}),
        "handled_failure": {"message": message, "type": type(error).__name__},
    }
    return _capture(
        level, user_id, tags, contexts, lambda _scope: sentry_sdk.capture_exception(error)
    )


def capture_telegram_storage_upload_failure(
    meme: dict[str, Any],
    *,
    reason: str,
    attempt: int | None = None,
    max_attempts: int | None = None,
    content_size: int | None = None,
    error: BaseException | None = None,
    observability_context: dict[str, Any] | None = None,
) -> str | None:
    contexts = dict(observability_context or {})
    contexts["telegram_storage_upload"] = {
        "reason": reason,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "content_size": content_size,
        "meme_id": meme.get("id"),
        "meme_type": meme.get("type"),
    }
    return capture_handled_issue(
        "telegram_storage_upload.failed",
        level="warning",
        user_id=(contexts.get("user_upload") or {}).get("user_id"),
        tags={
            "ff.module": "telegram_storage_upload",
            "ff.failure_kind": reason,
            "meme.type": meme.get("type"),
            "error.type": type(error).__name__ if error else None,
        },
        contexts=contexts,
        error=error,
    )


def sentry_log_extra(context: dict[str, Any] | None = None, **values: Any) -> dict[str, Any]:
    """Flatten safe context into LogRecord extras for Sentry Logs and JSON logs."""
    items = [
        (f"{namespace}_{key}", value)
        for namespace, namespace_values in (context or {}).items()
        if isinstance(namespace_values, dict)
        for key, value in namespace_values.items()
    ] + list(values.items())
    return {
        f"ff_{key}": _clean_scalar(value)
        for key, value in items
        if _is_scalar(value) and not _is_sensitive_key(key)
    }


def _capture(level, user_id, tags, contexts, send) -> str | None:
    try:
        with sentry_sdk.new_scope() as scope:
            scope.set_level(level)
            if user_id is not None:
                scope.set_user({"id": str(user_id)})
            for key, value in (tags or {}).items():
                if value is not None:
                    scope.set_tag(key, str(_clean_scalar(value))[:200].replace("\n", " "))
            for key, value in (contexts or {}).items():
                scope.set_context(key, _clean_context(value))
            return send(scope)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to capture handled Sentry event")
        return None


def _telegram_update_type(update: Any) -> str:
    return next((f for f in UPDATE_TYPES if getattr(update, f, None) is not None), "unknown")


def _callback_route(callback_data: Any) -> str | None:
    if not isinstance(callback_data, str) or not callback_data:
        return None
    return re.sub(r"\d+", "{id}", callback_data)[:120]


def _clean_context(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[Filtered]" if _is_sensitive_key(str(key)) else _clean_context(item)
            for key, item in value.items()
            if str(key) not in RAW_FILE_ID_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_clean_context(item) for item in value[:10]]
    return _clean_scalar(value)


def _clean_scalar(value: Any) -> Any:
    if isinstance(value, Enum):
        value = value.value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value)
    if len(text) > MAX_CONTEXT_STRING_LENGTH:
        return text[:MAX_CONTEXT_STRING_LENGTH] + "...[truncated]"
    return text


def _scrub_text(text: str) -> str:
    for pattern, replacement in TEXT_SCRUBBERS:
        text = pattern.sub(replacement, text)
    if len(text) > MAX_LOG_BODY_LENGTH:
        return text[:MAX_LOG_BODY_LENGTH] + "...[truncated]"
    return text


def _is_sensitive_key(key: str) -> bool:
    return any(part in key.lower() for part in SENSITIVE_KEY_PARTS)


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (Enum, str, int, float, bool))
