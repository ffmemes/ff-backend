from collections import defaultdict
from unittest.mock import AsyncMock, patch

import pytest

from src.tgbot.user_info import get_user_info


@pytest.mark.asyncio
async def test_get_user_info_refreshes_cache_without_account_age_days():
    cached_user_info = {"nmemes_sent": 8, "nsessions": 1}
    refreshed_user_info = defaultdict(
        lambda: None,
        {"nmemes_sent": 8, "nsessions": 1, "account_age_days": 31},
    )

    with (
        patch(
            "src.tgbot.user_info.get_cached_user_info",
            new_callable=AsyncMock,
            return_value=cached_user_info,
        ),
        patch(
            "src.tgbot.user_info.update_user_info_cache",
            new_callable=AsyncMock,
            return_value=refreshed_user_info,
        ) as update_cache,
    ):
        user_info = await get_user_info(123)

    update_cache.assert_awaited_once_with(123)
    assert user_info["id"] == 123
    assert user_info["account_age_days"] == 31


@pytest.mark.asyncio
async def test_get_user_info_uses_cache_with_required_account_age_days():
    cached_user_info = {"nmemes_sent": 8, "nsessions": 1, "account_age_days": 12}

    with (
        patch(
            "src.tgbot.user_info.get_cached_user_info",
            new_callable=AsyncMock,
            return_value=cached_user_info,
        ),
        patch("src.tgbot.user_info.update_user_info_cache", new_callable=AsyncMock) as update_cache,
    ):
        user_info = await get_user_info(123)

    update_cache.assert_not_awaited()
    assert user_info["id"] == 123
    assert user_info["account_age_days"] == 12
