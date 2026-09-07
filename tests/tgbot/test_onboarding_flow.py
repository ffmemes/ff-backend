from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.tgbot.handlers.onboarding import onboarding_flow


@pytest.mark.asyncio
async def test_onboarding_flow_sends_welcome_then_first_meme_without_countdown():
    sent: list[str] = []
    welcome = "Like memes you like"

    async def send_welcome(text, **kwargs):
        sent.append(text)
        return SimpleNamespace()

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42, send_message=send_welcome),
    )

    with (
        patch(
            "src.tgbot.handlers.onboarding.update_user_info_cache",
            new_callable=AsyncMock,
            return_value={"nmemes_sent": 0, "interface_lang": "en"},
        ),
        patch(
            "src.tgbot.handlers.onboarding.next_message",
            new_callable=AsyncMock,
        ) as next_message,
        patch(
            "src.tgbot.handlers.onboarding.localizer.t",
            return_value=welcome,
        ),
    ):
        await onboarding_flow(update, bot=object())

    assert sent == [welcome]
    next_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_onboarding_flow_skips_welcome_after_early_memes():
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42, send_message=AsyncMock()),
    )

    with (
        patch(
            "src.tgbot.handlers.onboarding.update_user_info_cache",
            new_callable=AsyncMock,
            return_value={"nmemes_sent": 4, "interface_lang": "en"},
        ),
        patch(
            "src.tgbot.handlers.onboarding.next_message",
            new_callable=AsyncMock,
        ) as next_message,
    ):
        await onboarding_flow(update, bot=object())

    update.effective_user.send_message.assert_not_called()
    next_message.assert_awaited_once()
