from fastapi import Header

from src.config import settings
from src.exceptions import PermissionDenied


async def validate_webhook_secret(
    x_telegram_bot_api_secret_token: str | None = Header(None),
) -> None:
    if x_telegram_bot_api_secret_token == settings.TELEGRAM_BOT_WEBHOOK_SECRET:
        return

    raise PermissionDenied()
