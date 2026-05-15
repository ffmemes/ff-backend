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

MAX_CONTEXT_STRING_LENGTH = 500
MAX_LOG_BODY_LENGTH = 2000
SENTRY_LOG_PARAMETER_PREFIX = "sentry.message.parameter."
URL_PATTERN = re.compile(r"https?://[^\s)>\]]+")
BEARER_TOKEN_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|authorization|bot[_-]?token|dsn|password|secret|token)"
    r"\s*[:=]\s*([^\s,;]+)"
)
TELEGRAM_BOT_TOKEN_PATTERN = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b")
HIGH_ENTROPY_TOKEN_PATTERN = re.compile(
    r"\b(?=[A-Za-z0-9_-]{32,}\b)(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9_-]+\b"
)


def before_send(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any] | None:
    """Remove sensitive exception payloads before Sentry stores an event."""
    _drop_exception_frame_vars(event)
    return event


def before_send_log(log: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any] | None:
    """Scrub searchable Sentry Logs before they leave the process."""
    attributes = log.get("attributes")
    if isinstance(attributes, dict):
        log["attributes"] = {
            key: _scrub_log_attribute(key, value) for key, value in attributes.items()
        }

    body = log.get("body")
    if isinstance(body, str):
        log["body"] = _scrub_log_text(body)

    return log


@contextmanager
def telegram_update_scope(update: Any) -> Iterator[None]:
    """Attach Telegram update context to Sentry events produced by one webhook."""
    with sentry_sdk.new_scope() as scope:
        user_id = _get_attr(getattr(update, "effective_user", None), "id")
        if user_id is not None:
            scope.set_user({"id": str(user_id)})

        update_type = _telegram_update_type(update)
        chat = getattr(update, "effective_chat", None)
        message = getattr(update, "effective_message", None)
        callback_query = getattr(update, "callback_query", None)
        callback_route = _callback_route(getattr(callback_query, "data", None))

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
                    "update_id": _get_attr(update, "update_id"),
                    "update_type": update_type,
                    "user_id": user_id,
                    "chat_id": _get_attr(chat, "id"),
                    "chat_type": _get_attr(chat, "type"),
                    "message_id": _get_attr(message, "message_id"),
                    "callback_route": callback_route,
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
                "type": _enum_value(meme.get("type")),
                "status": _enum_value(meme.get("status")),
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
                "file_size": media.get("file_size"),
                "mime_type": media.get("mime_type"),
                "duration": media.get("duration"),
                "width": media.get("width"),
                "height": media.get("height"),
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
    try:
        with sentry_sdk.new_scope() as scope:
            scope.set_level(level)
            if user_id is not None:
                scope.set_user({"id": str(user_id)})

            for key, value in (tags or {}).items():
                if value is not None:
                    scope.set_tag(key, _tag_value(value))

            for key, value in (contexts or {}).items():
                scope.set_context(key, _clean_context(value))

            if error is not None:
                scope.set_context(
                    "error",
                    _clean_context(
                        {
                            "type": type(error).__name__,
                            "message": str(error),
                        }
                    ),
                )

            return scope.capture_message(message, level=level)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to capture handled Sentry issue")
        return None


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
    try:
        with sentry_sdk.new_scope() as scope:
            scope.set_level(level)
            if user_id is not None:
                scope.set_user({"id": str(user_id)})

            for key, value in (tags or {}).items():
                if value is not None:
                    scope.set_tag(key, _tag_value(value))

            for key, value in (contexts or {}).items():
                scope.set_context(key, _clean_context(value))

            scope.set_context(
                "handled_failure",
                _clean_context(
                    {
                        "message": message,
                        "type": type(error).__name__,
                    }
                ),
            )
            return sentry_sdk.capture_exception(error)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to capture handled Sentry exception")
        return None


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
    contexts["telegram_storage_upload"] = _clean_context(
        {
            "reason": reason,
            "attempt": attempt,
            "max_attempts": max_attempts,
            "content_size": content_size,
            "meme_id": meme.get("id"),
            "meme_type": _enum_value(meme.get("type")),
        }
    )
    user_id = _context_user_id(observability_context)

    return capture_handled_issue(
        "telegram_storage_upload.failed",
        level="warning",
        user_id=user_id,
        tags={
            "ff.module": "telegram_storage_upload",
            "ff.failure_kind": reason,
            "meme.type": _enum_value(meme.get("type")),
            "error.type": type(error).__name__ if error else None,
        },
        contexts=contexts,
        error=error,
    )


def sentry_log_extra(context: dict[str, Any] | None = None, **values: Any) -> dict[str, Any]:
    """Flatten safe context into LogRecord extras for Sentry Logs and JSON logs."""
    extra: dict[str, Any] = {}
    for namespace, namespace_values in (context or {}).items():
        if not isinstance(namespace_values, dict):
            continue
        for key, value in namespace_values.items():
            if _is_scalar(value) and not _is_sensitive_key(key):
                extra[f"ff_{namespace}_{key}"] = _clean_scalar(value)

    for key, value in values.items():
        if _is_scalar(value) and not _is_sensitive_key(key):
            extra[f"ff_{key}"] = _clean_scalar(value)

    return extra


def _telegram_update_type(update: Any) -> str:
    for field in (
        "message",
        "edited_message",
        "callback_query",
        "inline_query",
        "chosen_inline_result",
        "pre_checkout_query",
        "chat_member",
        "my_chat_member",
        "chat_boost",
    ):
        if getattr(update, field, None) is not None:
            return field
    return "unknown"


def _callback_route(callback_data: Any) -> str | None:
    if not isinstance(callback_data, str) or not callback_data:
        return None
    route = re.sub(r"\d+", "{id}", callback_data)
    return route[:120]


def _context_user_id(context: dict[str, Any] | None) -> int | str | None:
    user_upload = (context or {}).get("user_upload")
    if isinstance(user_upload, dict):
        return user_upload.get("user_id")
    return None


def _clean_context(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[Filtered]" if _is_sensitive_key(str(key)) else _clean_context(item)
            for key, item in value.items()
            if not _is_raw_telegram_file_id_key(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [_clean_context(item) for item in value[:10]]
    return _clean_scalar(value)


def _clean_scalar(value: Any) -> Any:
    value = _enum_value(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value)
    if len(text) > MAX_CONTEXT_STRING_LENGTH:
        return text[:MAX_CONTEXT_STRING_LENGTH] + "...[truncated]"
    return text


def _drop_exception_frame_vars(event: dict[str, Any]) -> None:
    exception = event.get("exception")
    if not isinstance(exception, dict):
        return

    values = exception.get("values")
    if not isinstance(values, list):
        return

    for exception_value in values:
        if not isinstance(exception_value, dict):
            continue
        stacktrace = exception_value.get("stacktrace")
        if not isinstance(stacktrace, dict):
            continue
        frames = stacktrace.get("frames")
        if not isinstance(frames, list):
            continue
        for frame in frames:
            if isinstance(frame, dict):
                frame.pop("vars", None)


def _scrub_log_attribute(key: str, value: Any) -> Any:
    if _is_sensitive_key(key) or _is_sentry_log_parameter_key(key):
        return "[Filtered]"
    if isinstance(value, str):
        return _scrub_log_text(value)
    return value


def _scrub_log_text(text: str) -> str:
    scrubbed = URL_PATTERN.sub("[Filtered]", text)
    scrubbed = BEARER_TOKEN_PATTERN.sub("Bearer [Filtered]", scrubbed)
    scrubbed = SECRET_ASSIGNMENT_PATTERN.sub(r"\1=[Filtered]", scrubbed)
    scrubbed = TELEGRAM_BOT_TOKEN_PATTERN.sub("[Filtered]", scrubbed)
    scrubbed = HIGH_ENTROPY_TOKEN_PATTERN.sub("[Filtered]", scrubbed)
    if len(scrubbed) > MAX_LOG_BODY_LENGTH:
        return scrubbed[:MAX_LOG_BODY_LENGTH] + "...[truncated]"
    return scrubbed


def _tag_value(value: Any) -> str:
    return str(_clean_scalar(value))[:200].replace("\n", " ")


def _enum_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _is_sentry_log_parameter_key(key: str) -> bool:
    return key.lower().startswith(SENTRY_LOG_PARAMETER_PREFIX)


def _is_raw_telegram_file_id_key(key: str) -> bool:
    return key in {"file_id", "telegram_file_id", "raw_file_id"}


def _is_scalar(value: Any) -> bool:
    value = _enum_value(value)
    return value is None or isinstance(value, (str, int, float, bool))


def _get_attr(value: Any, attr: str) -> Any:
    return getattr(value, attr, None) if value is not None else None
