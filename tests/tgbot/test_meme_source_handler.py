from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.storage.constants import MemeSourceType
from src.tgbot.handlers.moderator import meme_source


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
