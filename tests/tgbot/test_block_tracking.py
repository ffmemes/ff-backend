import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.tgbot import service
from src.tgbot.constants import UserType
from src.tgbot.handlers import block
from src.tgbot.repo import users as users_repo


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
            "type": UserType.USER.value,
            "blocked_bot_at": datetime(2026, 4, 27, 20, 0, 27),
        }
    )
    # mark_user_blocked lives in repo.users; patch that module's globals.
    monkeypatch.setattr(
        users_repo,
        "get_user_by_id",
        AsyncMock(return_value={"id": 10001, "type": UserType.USER.value}),
    )
    monkeypatch.setattr(users_repo, "update_user", update_user)

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
    assert "type" not in update_user.await_args.kwargs
    blocked_bot_at = update_user.await_args.kwargs["blocked_bot_at"]
    assert blocked_bot_at == datetime(2026, 4, 27, 20, 0, 27)
    assert blocked_bot_at.tzinfo is None


@pytest.mark.asyncio
async def test_mark_user_blocked_preserves_admin_type(monkeypatch) -> None:
    update_user = AsyncMock(
        return_value={
            "id": 49820636,
            "type": UserType.ADMIN.value,
            "blocked_bot_at": datetime(2026, 4, 27, 20, 0, 27),
        }
    )
    monkeypatch.setattr(
        users_repo,
        "get_user_by_id",
        AsyncMock(return_value={"id": 49820636, "type": UserType.ADMIN.value}),
    )
    monkeypatch.setattr(users_repo, "update_user", update_user)

    monkeypatch.setitem(
        sys.modules,
        "src.tgbot.user_info",
        SimpleNamespace(update_user_info_cache=AsyncMock()),
    )

    await service.mark_user_blocked(
        user_id=49820636,
        source="my_chat_member",
        when=datetime(2026, 4, 27, 20, 0, 27, tzinfo=timezone.utc),
    )

    update_user.assert_awaited_once()
    assert update_user.await_args.kwargs == {"blocked_bot_at": datetime(2026, 4, 27, 20, 0, 27)}


@pytest.mark.asyncio
async def test_handle_user_blocked_bot_escapes_admin_log_html(monkeypatch) -> None:
    messages = []
    user = SimpleNamespace(id=10002, name="<3", language_code="<en>")
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=10002),
        my_chat_member=SimpleNamespace(
            from_user=user,
            date=datetime(2026, 5, 11, 7, 18, 19, tzinfo=timezone.utc),
        ),
    )
    context = SimpleNamespace(bot=object())

    monkeypatch.setattr(
        block,
        "mark_user_blocked",
        AsyncMock(
            return_value={
                "created_at": datetime(2024, 2, 18, 12, 57, 50),
                "nickname": "<boss>",
            }
        ),
    )

    async def fake_log(message, _bot):
        messages.append(message)

    monkeypatch.setattr(block, "log", fake_log)

    await block.handle_user_blocked_bot(update, context)

    assert "&lt;3" in messages[0]
    assert "&lt;en&gt;" in messages[0]
    assert "&lt;boss&gt;" in messages[0]
