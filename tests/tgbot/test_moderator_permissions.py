from unittest.mock import AsyncMock, patch

import pytest

from src.tgbot.exceptions import UserNotFound
from src.tgbot.handlers.moderator.permissions import get_moderator_user_info


@pytest.mark.asyncio
async def test_get_moderator_user_info_refreshes_stale_non_moderator_cache() -> None:
    with (
        patch(
            "src.tgbot.handlers.moderator.permissions.get_user_info",
            new=AsyncMock(return_value={"type": "user"}),
        ),
        patch(
            "src.tgbot.handlers.moderator.permissions.update_user_info_cache",
            new=AsyncMock(return_value={"type": "moderator"}),
        ) as refresh,
    ):
        user_info = await get_moderator_user_info(1007266539)

    refresh.assert_awaited_once_with(1007266539)
    assert user_info is not None
    assert user_info["type"] == "moderator"


@pytest.mark.asyncio
async def test_get_moderator_user_info_accepts_admin() -> None:
    with (
        patch(
            "src.tgbot.handlers.moderator.permissions.get_user_info",
            new=AsyncMock(return_value={"type": "admin"}),
        ),
        patch(
            "src.tgbot.handlers.moderator.permissions.update_user_info_cache",
            new=AsyncMock(),
        ) as refresh,
    ):
        user_info = await get_moderator_user_info(49820636)

    refresh.assert_not_awaited()
    assert user_info is not None
    assert user_info["type"] == "admin"


@pytest.mark.asyncio
async def test_get_moderator_user_info_denies_missing_user() -> None:
    with patch(
        "src.tgbot.handlers.moderator.permissions.get_user_info",
        new=AsyncMock(side_effect=UserNotFound(42)),
    ):
        assert await get_moderator_user_info(42) is None
