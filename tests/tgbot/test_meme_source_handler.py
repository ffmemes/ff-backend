import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.storage.constants import MemeSourceStatus, MemeSourceType
from src.tgbot.constants import MEME_SOURCE_SET_STATUS_REGEXP
from src.tgbot.handlers.moderator import meme_source
from src.tgbot.senders.keyboards import meme_source_change_status_keyboard


@pytest.mark.parametrize(
    "text,expected_url,expected_type",
    [
        (
            "https://t.me/cozy_abomination",
            "https://t.me/cozy_abomination",
            MemeSourceType.TELEGRAM,
        ),
        (
            "t.me/Cozy_Abomination/42?single",
            "https://t.me/cozy_abomination",
            MemeSourceType.TELEGRAM,
        ),
        (
            "source: http://telegram.me/Cozy_Abomination/42",
            "https://t.me/cozy_abomination",
            MemeSourceType.TELEGRAM,
        ),
        (
            "https://vk.com/example_group?from=share",
            "https://vk.com/example_group",
            MemeSourceType.VK,
        ),
        (
            "https://www.instagram.com/example.page/?utm_source=ig_web_copy_link",
            "https://www.instagram.com/example.page/",
            MemeSourceType.INSTAGRAM,
        ),
    ],
)
def test_parse_meme_source_link_accepts_common_source_formats(
    text: str,
    expected_url: str,
    expected_type: MemeSourceType,
) -> None:
    parsed = meme_source.parse_meme_source_link(text)

    assert parsed is not None
    assert parsed.url == expected_url
    assert parsed.type == expected_type


@pytest.mark.parametrize(
    "text",
    [
        "https://t.me/+private_invite",
        "https://t.me/joinchat/abcdef",
        "just a message",
        "",
    ],
)
def test_parse_meme_source_link_rejects_unsupported_sources(text: str) -> None:
    assert meme_source.parse_meme_source_link(text) is None


def test_meme_source_status_keyboard_uses_stable_callback_values() -> None:
    keyboard = meme_source_change_status_keyboard(
        meme_source_id=203,
        current_status=MemeSourceStatus.PARSING_ENABLED.value,
    )

    buttons = [row[0] for row in keyboard.inline_keyboard]
    callback_data = [button.callback_data for button in buttons]

    assert "ms:203:set_status:snoozed" in callback_data
    assert "ms:203:set_status:parsing_enabled" not in callback_data
    assert all(re.match(MEME_SOURCE_SET_STATUS_REGEXP, data) for data in callback_data)
    assert all("MemeSourceStatus." not in data for data in callback_data)
    assert {button.text for button in buttons} == {
        "➡️ in_moderation",
        "➡️ parsing_disabled",
        "➡️ snoozed",
    }


@pytest.mark.parametrize(
    "callback_data,expected",
    [
        ("ms:203:set_status:snoozed", (203, "snoozed")),
        ("ms:203:set_status:MemeSourceStatus.SNOOZED", (203, "snoozed")),
    ],
)
def test_parse_meme_source_status_callback_data_accepts_current_and_legacy_buttons(
    callback_data: str,
    expected: tuple[int, str],
) -> None:
    assert re.match(MEME_SOURCE_SET_STATUS_REGEXP, callback_data)
    assert meme_source.parse_meme_source_status_callback_data(callback_data) == expected


@pytest.mark.asyncio
async def test_handle_meme_source_link_refreshes_to_moderator_and_opens_admin_card() -> None:
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=1007266539),
        message=SimpleNamespace(
            text="please add t.me/Cozy_Abomination/42?single",
            reply_text=AsyncMock(),
        ),
    )
    context = SimpleNamespace()
    source_row = {"id": 123, "url": "https://t.me/cozy_abomination"}

    with (
        patch(
            "src.tgbot.handlers.moderator.meme_source.get_moderator_user_info",
            new=AsyncMock(return_value={"type": "moderator"}),
        ),
        patch(
            "src.tgbot.handlers.moderator.meme_source.get_or_create_meme_source",
            new=AsyncMock(return_value=source_row),
        ) as get_or_create,
        patch(
            "src.tgbot.handlers.moderator.meme_source.meme_source_admin_pipeline",
            new=AsyncMock(),
        ) as admin_pipeline,
    ):
        await meme_source.handle_meme_source_link(update, context)

    get_or_create.assert_awaited_once()
    assert get_or_create.await_args.kwargs["url"] == "https://t.me/cozy_abomination"
    assert get_or_create.await_args.kwargs["type"] == MemeSourceType.TELEGRAM
    admin_pipeline.assert_awaited_once_with(source_row, update)
    update.message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_meme_source_link_tells_non_moderator_why_nothing_happens() -> None:
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42),
        message=SimpleNamespace(text="https://t.me/cozy_abomination", reply_text=AsyncMock()),
    )
    context = SimpleNamespace()

    with patch(
        "src.tgbot.handlers.moderator.meme_source.get_moderator_user_info",
        new=AsyncMock(return_value=None),
    ):
        await meme_source.handle_meme_source_link(update, context)

    update.message.reply_text.assert_awaited_once_with("Only moderators can manage meme sources.")
