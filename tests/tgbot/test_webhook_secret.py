import pytest

from src.config import settings
from src.exceptions import PermissionDenied
from src.tgbot.dependencies import validate_webhook_secret


async def test_webhook_secret(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_WEBHOOK_SECRET", "s3cret")
    await validate_webhook_secret("s3cret")
    for bad in (None, "", "wrong"):
        with pytest.raises(PermissionDenied):
            await validate_webhook_secret(bad)

    # Unset secret must fail closed, even for a header-less request.
    monkeypatch.setattr(settings, "TELEGRAM_BOT_WEBHOOK_SECRET", None)
    with pytest.raises(PermissionDenied):
        await validate_webhook_secret(None)
