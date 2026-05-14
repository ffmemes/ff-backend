from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.tgbot.handlers.upload import moderation


def _update(
    *,
    user_id: int = 1,
    chat_id: int = -100,
    data: str = "upload:42:review:reject",
):
    message = SimpleNamespace(
        chat_id=chat_id,
        caption="review caption",
        edit_caption=AsyncMock(),
        edit_reply_markup=AsyncMock(),
    )
    query = SimpleNamespace(
        data=data,
        message=message,
        answer=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )
    user = SimpleNamespace(id=user_id, name="Reviewer")
    return SimpleNamespace(callback_query=query, effective_user=user), message, query


@pytest.mark.asyncio
async def test_self_review_restores_review_buttons(monkeypatch):
    monkeypatch.setattr(moderation.settings, "UPLOADED_MEMES_REVIEW_CHAT_ID", "-100")
    update, message, query = _update(user_id=7)

    with (
        patch.object(
            moderation,
            "get_meme_raw_upload_by_id",
            new=AsyncMock(return_value={"id": 42, "user_id": 7}),
        ),
        patch.object(moderation, "update_meme_by_upload_id", new=AsyncMock()) as update_meme,
    ):
        await moderation.handle_uploaded_meme_review_button(update, SimpleNamespace(bot=None))

    query.answer.assert_awaited_once_with("You can't review your own memes")
    message.edit_reply_markup.assert_awaited_once()
    assert message.edit_reply_markup.await_args.kwargs["reply_markup"] is not None
    update_meme.assert_not_awaited()


@pytest.mark.asyncio
async def test_review_callback_outside_upload_review_chat_is_ignored(monkeypatch):
    monkeypatch.setattr(moderation.settings, "UPLOADED_MEMES_REVIEW_CHAT_ID", "-100")
    update, _message, query = _update(chat_id=-200)

    with patch.object(
        moderation,
        "get_meme_raw_upload_by_id",
        new=AsyncMock(),
    ) as get_upload:
        await moderation.handle_uploaded_meme_review_button(update, SimpleNamespace(bot=None))

    query.answer.assert_awaited_once_with("This review button belongs to the upload review chat")
    get_upload.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_review_chat_member_can_reject_without_moderator_user_type(monkeypatch):
    monkeypatch.setattr(moderation.settings, "UPLOADED_MEMES_REVIEW_CHAT_ID", "-100")
    update, message, query = _update(user_id=8)
    context = SimpleNamespace(bot=AsyncMock())

    with (
        patch.object(
            moderation,
            "get_meme_raw_upload_by_id",
            new=AsyncMock(return_value={"id": 42, "user_id": 7, "message_id": 100}),
        ),
        patch.object(
            moderation,
            "update_meme_by_upload_id",
            new=AsyncMock(return_value={"id": 99}),
        ) as update_meme,
        patch.object(moderation, "pay_if_not_paid_with_alert", new=AsyncMock()) as pay,
        patch.object(moderation, "_notify_uploader", new=AsyncMock()) as notify,
        patch.object(
            moderation,
            "get_user_info",
            new=AsyncMock(return_value={"interface_lang": "en"}),
        ) as get_user_info,
    ):
        await moderation.handle_uploaded_meme_review_button(update, context)

    query.answer.assert_awaited_once_with()
    assert update_meme.await_count == 2
    pay.assert_awaited_once()
    message.edit_caption.assert_awaited_once()
    notify.assert_awaited_once()
    get_user_info.assert_awaited_once_with(7)
