from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.tgbot.handlers import broken


@pytest.mark.asyncio
async def test_broken_callback_query_uses_user_interface_language() -> None:
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=49820636, language_code="en", send_message=AsyncMock()),
        callback_query=SimpleNamespace(data="ms:203:set_status:old-value"),
    )
    context = SimpleNamespace()

    with patch(
        "src.tgbot.handlers.broken.get_user_info",
        new=AsyncMock(return_value={"interface_lang": "ru"}),
    ):
        await broken.handle_broken_callback_query(update, context)

    update.effective_user.send_message.assert_awaited_once_with(
        "🔄 Бот обновился. Нажми /start, чтобы продолжить."
    )
