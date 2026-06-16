from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from src.tgbot.sharing import (
    MEME_SHARE_BUTTON_INLINE,
    MEME_SHARE_BUTTON_URL,
    build_meme_share_assignment,
    build_meme_share_button,
    get_meme_inline_query,
    get_meme_share_link,
    get_meme_share_url,
    get_or_assign_meme_share_button_variant,
    parse_meme_share_deep_link,
)


def test_parse_meme_share_deep_link():
    parsed = parse_meme_share_deep_link("m_10001_20002")

    assert parsed is not None
    assert parsed.sharer_user_id == 10001
    assert parsed.meme_id == 20002

    legacy_parsed = parse_meme_share_deep_link("s_10001_20002")
    assert legacy_parsed is not None
    assert legacy_parsed.sharer_user_id == 10001
    assert legacy_parsed.meme_id == 20002

    assert parse_meme_share_deep_link("m_10001_20002_extra") is None
    assert parse_meme_share_deep_link("ir_10001_20002") is None


def test_get_meme_share_url_wraps_start_deep_link():
    share_url = get_meme_share_url(10001, 20002, "en")
    parsed = urlparse(share_url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "t.me"
    assert parsed.path == "/share/url"
    assert query["url"] == [get_meme_share_link(10001, 20002)]
    assert query["text"] == ["Check out this meme"]
    assert "start=m_10001_20002" in query["url"][0]


def test_build_url_share_button():
    button = build_meme_share_button(
        meme_id=20002,
        user_id=10001,
        text="Send to a friend",
        variant=MEME_SHARE_BUTTON_URL,
        interface_lang="en",
    )

    assert button.text == "Send to a friend"
    assert button.url.startswith("https://t.me/share/url?")
    assert button.switch_inline_query_chosen_chat is None


def test_build_inline_share_button_prefills_exact_meme_query():
    button = build_meme_share_button(
        meme_id=20002,
        user_id=10001,
        text="Send to a friend",
        variant=MEME_SHARE_BUTTON_INLINE,
        interface_lang="en",
    )

    assert button.url is None
    assert button.switch_inline_query_chosen_chat.query == get_meme_inline_query(20002)
    assert button.switch_inline_query_chosen_chat.allow_user_chats is True
    assert button.switch_inline_query_chosen_chat.allow_group_chats is True
    assert button.switch_inline_query_chosen_chat.allow_channel_chats is True


def test_build_meme_share_assignment_respects_canary_bounds():
    variant, metadata = build_meme_share_assignment(10001, inline_percent=0)

    assert variant == MEME_SHARE_BUTTON_URL
    assert metadata["inline_canary_percent"] == 0

    variant, metadata = build_meme_share_assignment(10001, inline_percent=100)

    assert variant == MEME_SHARE_BUTTON_INLINE
    assert metadata["inline_canary_percent"] == 100

    variant, metadata = build_meme_share_assignment(10001, inline_percent=150)

    assert variant == MEME_SHARE_BUTTON_INLINE
    assert metadata["inline_canary_percent"] == 100


@pytest.mark.asyncio
async def test_inline_share_variant_can_be_disabled_by_flag():
    with patch("src.tgbot.sharing.settings.TELEGRAM_INLINE_SHARE_ENABLED", False), patch(
        "src.tgbot.sharing.get_experiment_variant",
        new_callable=AsyncMock,
    ) as get_variant:
        variant = await get_or_assign_meme_share_button_variant(10001)

    assert variant == MEME_SHARE_BUTTON_URL
    get_variant.assert_not_awaited()


@pytest.mark.asyncio
async def test_inline_share_zero_canary_does_not_assign_experiment():
    with (
        patch("src.tgbot.sharing.settings.TELEGRAM_INLINE_SHARE_ENABLED", True),
        patch("src.tgbot.sharing.settings.TELEGRAM_INLINE_SHARE_CANARY_PERCENT", 0),
        patch("src.tgbot.sharing.get_experiment_variant", new_callable=AsyncMock) as get_variant,
    ):
        variant = await get_or_assign_meme_share_button_variant(10001)

    assert variant == MEME_SHARE_BUTTON_URL
    get_variant.assert_not_awaited()


@pytest.mark.asyncio
async def test_inline_share_canary_assigns_inline_variant_when_bucketed_in():
    with (
        patch("src.tgbot.sharing.settings.TELEGRAM_INLINE_SHARE_ENABLED", True),
        patch("src.tgbot.sharing.settings.TELEGRAM_INLINE_SHARE_CANARY_PERCENT", 100),
        patch(
            "src.tgbot.sharing.get_experiment_variant",
            new_callable=AsyncMock,
            return_value=None,
        ) as get_variant,
        patch(
            "src.tgbot.sharing.assign_experiment",
            new_callable=AsyncMock,
            return_value=True,
        ) as assign,
    ):
        variant = await get_or_assign_meme_share_button_variant(10001)

    assert variant == MEME_SHARE_BUTTON_INLINE
    get_variant.assert_awaited_once_with(10001, "meme_share_button")
    assign.assert_awaited_once()
