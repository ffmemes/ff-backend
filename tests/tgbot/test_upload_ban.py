from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from telegram.constants import ChatType

from src.tgbot.constants import UserType
from src.tgbot.handlers.upload.service import get_user_upload_ban_status
from src.tgbot.handlers.upload.upload_meme import (
    get_upload_banned_message,
    handle_message_with_meme,
)

UPLOAD_BANNED_USER_ID = 13001


def _make_private_upload_update(user_id: int = UPLOAD_BANNED_USER_ID):
    message = SimpleNamespace(
        reply_text=AsyncMock(),
        forward_from=None,
        forward_origin=None,
        text=None,
        caption=None,
    )
    return SimpleNamespace(
        message=message,
        effective_chat=SimpleNamespace(type=ChatType.PRIVATE),
        effective_user=SimpleNamespace(id=user_id),
    )


def _make_context():
    return SimpleNamespace(bot=SimpleNamespace(id=999))


@pytest.mark.asyncio
async def test_get_user_upload_ban_status_reads_type_and_invites():
    expected_status = {
        "type": UserType.UPLOAD_BANNED.value,
        "invited_users": 2,
    }
    with patch(
        "src.tgbot.handlers.upload.service.fetch_one",
        new=AsyncMock(return_value=expected_status),
    ) as fetch_one:
        status = await get_user_upload_ban_status(UPLOAD_BANNED_USER_ID)

    assert status == expected_status
    query, params = fetch_one.await_args.args
    assert params == {"user_id": UPLOAD_BANNED_USER_ID}
    assert "LEFT JOIN" in str(query)
    assert "inviter_id" in str(query)


@pytest.mark.asyncio
async def test_upload_banned_user_gets_invite_count_message():
    update = _make_private_upload_update()
    context = _make_context()

    with (
        patch(
            "src.tgbot.handlers.upload.upload_meme.get_user_info",
            new=AsyncMock(
                return_value={
                    "type": UserType.USER.value,
                    "nmemes_sent": 100,
                    "interface_lang": "ru",
                }
            ),
        ),
        patch(
            "src.tgbot.handlers.upload.upload_meme.get_user_upload_ban_status",
            new=AsyncMock(
                return_value={
                    "type": UserType.UPLOAD_BANNED.value,
                    "invited_users": 1,
                }
            ),
        ),
        patch(
            "src.tgbot.handlers.upload.upload_meme.create_meme_raw_upload",
            new=AsyncMock(),
        ) as create_meme_raw_upload,
    ):
        await handle_message_with_meme(update, context)

    update.message.reply_text.assert_awaited_once_with(get_upload_banned_message(1))
    create_meme_raw_upload.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_banned_user_can_upload_after_invite_threshold():
    update = _make_private_upload_update()
    context = _make_context()

    with (
        patch(
            "src.tgbot.handlers.upload.upload_meme.get_user_info",
            new=AsyncMock(
                return_value={
                    "type": UserType.USER.value,
                    "nmemes_sent": 100,
                    "interface_lang": "ru",
                }
            ),
        ),
        patch(
            "src.tgbot.handlers.upload.upload_meme.get_user_upload_ban_status",
            new=AsyncMock(
                return_value={
                    "type": UserType.UPLOAD_BANNED.value,
                    "invited_users": 20,
                }
            ),
        ),
        patch(
            "src.tgbot.handlers.upload.upload_meme.count_24h_uploaded_not_approved_memes",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "src.tgbot.handlers.upload.upload_meme.create_meme_raw_upload",
            new=AsyncMock(return_value={"id": 1}),
        ) as create_meme_raw_upload,
        patch(
            "src.tgbot.handlers.upload.upload_meme.check_if_user_follows_related_channel",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "src.tgbot.handlers.upload.upload_meme.get_related_channel_link",
            return_value="https://t.me/fastfoodmemes",
        ),
        patch("src.tgbot.handlers.upload.upload_meme.localizer.t", return_value="join {link}"),
    ):
        await handle_message_with_meme(update, context)

    create_meme_raw_upload.assert_awaited_once_with(update.message)
