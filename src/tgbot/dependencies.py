import secrets

from fastapi import Header

from src.config import settings
from src.exceptions import PermissionDenied


async def validate_webhook_secret(
    x_telegram_bot_api_secret_token: str | None = Header(None),
) -> None:
    # Fail closed: an unset secret must not let header-less requests through.
    expected = settings.TELEGRAM_BOT_WEBHOOK_SECRET
    if (
        expected
        and x_telegram_bot_api_secret_token
        and secrets.compare_digest(x_telegram_bot_api_secret_token, expected)
    ):
        return

    raise PermissionDenied()
