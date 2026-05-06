import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.tgbot import service
from src.tgbot.constants import UserType


def test_blocked_bot_at_timestamp_converts_aware_datetime_to_naive_utc() -> None:
    aware_time = datetime(2026, 4, 27, 23, 0, 27, tzinfo=timezone(timedelta(hours=3)))

    result = service._blocked_bot_at_timestamp(aware_time)

    assert result == datetime(2026, 4, 27, 20, 0, 27)
    assert result.tzinfo is None


@pytest.mark.asyncio
async def test_mark_user_blocked_sends_naive_timestamp_to_db(monkeypatch) -> None:
    update_user = AsyncMock(
        return_value={
            "id": 10001,
            "type": UserType.BLOCKED_BOT.value,
            "blocked_bot_at": datetime(2026, 4, 27, 20, 0, 27),
        }
    )
    monkeypatch.setattr(
        service,
        "get_user_by_id",
        AsyncMock(return_value={"id": 10001, "type": UserType.USER.value}),
    )
    monkeypatch.setattr(service, "update_user", update_user)

    monkeypatch.setitem(
        sys.modules,
        "src.tgbot.user_info",
        SimpleNamespace(update_user_info_cache=AsyncMock()),
    )

    await service.mark_user_blocked(
        user_id=10001,
        source="my_chat_member",
        when=datetime(2026, 4, 27, 20, 0, 27, tzinfo=timezone.utc),
    )

    update_user.assert_awaited_once()
    blocked_bot_at = update_user.await_args.kwargs["blocked_bot_at"]
    assert blocked_bot_at == datetime(2026, 4, 27, 20, 0, 27)
    assert blocked_bot_at.tzinfo is None
