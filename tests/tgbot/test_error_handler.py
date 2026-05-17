from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.error import NetworkError

from src.tgbot.handlers.error import send_stacktrace_to_tg_chat


async def test_error_handler_does_not_report_transient_telegram_errors_to_telegram():
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=12001, language_code="en"),
    )
    context = SimpleNamespace(
        error=NetworkError("All connection attempts failed"),
        bot=SimpleNamespace(send_message=AsyncMock()),
    )

    await send_stacktrace_to_tg_chat(update, context)

    context.bot.send_message.assert_not_awaited()
