from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, patch

import pytest

from src.tgbot.handlers.upload import moderation


def _update(
    *,
    user_id: int = 1,
    chat_id: int = -100,
    data: str = "upload:42:review:reject_not_funny",
):
    message = SimpleNamespace(
        chat_id=chat_id,
        caption="review caption",
        reply_markup=object(),
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


def test_review_keyboard_separates_approve_and_rejection_reasons():
    keyboard = moderation.review_keyboard(42).inline_keyboard

    assert len(keyboard) == 2
    assert [button.text for button in keyboard[0]] == ["✅ Всё ок"]
    assert [button.callback_data for button in keyboard[0]] == ["upload:42:review:approve"]
    assert [button.text for button in keyboard[1]] == [
        "❌ Не смешно",
        "🌐 Не тот язык",
        "🔁 Баян",
    ]
    assert [button.callback_data for button in keyboard[1]] == [
        "upload:42:review:reject_not_funny",
        "upload:42:review:reject_wrong_language",
        "upload:42:review:reject_duplicate",
    ]


def test_rejection_reason_messages_are_localized_in_english_and_russian():
    assert "wasn't funny enough" in moderation.localizer.t("upload.rejected_not_funny", "en")
    assert "не смешно" in moderation.localizer.t("upload.rejected_not_funny", "ru")
    assert "selected meme language doesn't match" in moderation.localizer.t(
        "upload.rejected_wrong_language", "en"
    )
    assert "выбран не тот язык" in moderation.localizer.t("upload.rejected_wrong_language", "ru")
    assert "already in our collection" in moderation.localizer.t("upload.rejected_duplicate", "en")
    assert "уже есть в нашей коллекции" in moderation.localizer.t("upload.rejected_duplicate", "ru")


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
    update, message, query = _update(
        user_id=8,
        data="upload:42:review:reject_wrong_language",
    )
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
            new=AsyncMock(return_value={"interface_lang": "ru"}),
        ) as get_user_info,
    ):
        await moderation.handle_uploaded_meme_review_button(update, context)

    query.answer.assert_awaited_once_with()
    update_meme.assert_awaited_once_with(42, status=moderation.MemeStatus.REJECTED)
    pay.assert_awaited_once()
    message.edit_caption.assert_awaited_once()
    assert "Не тот язык" in message.edit_caption.await_args.kwargs["caption"]
    notify.assert_awaited_once()
    assert "выбран не тот язык" in notify.await_args.args[2]
    get_user_info.assert_awaited_once_with(7)


@pytest.mark.asyncio
async def test_upload_review_duplicate_reason_notifies_uploader(monkeypatch):
    monkeypatch.setattr(moderation.settings, "UPLOADED_MEMES_REVIEW_CHAT_ID", "-100")
    update, message, query = _update(
        user_id=8,
        data="upload:42:review:reject_duplicate",
    )
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
        patch.object(moderation, "pay_if_not_paid_with_alert", new=AsyncMock()),
        patch.object(moderation, "_notify_uploader", new=AsyncMock()) as notify,
        patch.object(
            moderation,
            "get_user_info",
            new=AsyncMock(return_value={"interface_lang": "ru"}),
        ),
    ):
        await moderation.handle_uploaded_meme_review_button(update, context)

    query.answer.assert_awaited_once_with()
    update_meme.assert_awaited_once_with(42, status=moderation.MemeStatus.REJECTED)
    message.edit_caption.assert_awaited_once()
    assert "Баян" in message.edit_caption.await_args.kwargs["caption"]
    notify.assert_awaited_once()
    assert "уже есть в нашей коллекции" in notify.await_args.args[2]


@pytest.mark.asyncio
async def test_auto_review_does_not_revive_exact_file_id_duplicate(monkeypatch):
    meme = {
        "id": 10002,
        "type": moderation.MemeType.IMAGE,
        "telegram_file_id": "uploaded-file-id",
    }
    meme_upload = {"id": 42, "user_id": 10001, "message_id": 777}
    stored_duplicate = {
        **meme,
        "status": moderation.MemeStatus.DUPLICATE.value,
        "duplicate_of": 10000,
    }
    bot = AsyncMock()

    with (
        patch.object(moderation, "_get_uploader_lang", new=AsyncMock(return_value="ru")),
        patch.object(
            moderation,
            "download_meme_content_from_tg",
            new=AsyncMock(return_value=b"image"),
        ),
        patch.object(
            moderation,
            "add_watermark_to_meme_content",
            new=AsyncMock(return_value=b"watermarked"),
        ),
        patch.object(
            moderation,
            "upload_meme_content_to_tg",
            new=AsyncMock(return_value=stored_duplicate),
        ),
        patch.object(moderation, "update_meme", new=AsyncMock()) as update_meme,
        patch.object(
            moderation,
            "create_user_meme_reaction",
            new=AsyncMock(),
        ) as create_reaction,
        patch.object(moderation, "_notify_uploader", new=AsyncMock()) as notify,
        patch.object(moderation, "send_uploaded_meme_to_manual_review", new=AsyncMock()) as review,
    ):
        await moderation._uploaded_meme_auto_review(meme, meme_upload, bot, {})

    update_meme.assert_not_awaited()
    review.assert_not_awaited()
    create_reaction.assert_awaited_once_with(
        10001,
        10000,
        "uploaded_meme",
        reaction_id=1,
        reacted_at=ANY,
    )
    notify.assert_awaited_once()
    assert "повтор" in notify.await_args.args[2].lower()


@pytest.mark.asyncio
async def test_inline_ocr_duplicate_uses_dedup_resolver(monkeypatch):
    meme = {
        "id": 10002,
        "type": moderation.MemeType.IMAGE,
        "telegram_file_id": "uploaded-file-id",
    }
    refreshed = {
        **meme,
        "ocr_result": {"text": "same visible meme text"},
    }

    with (
        patch.object(moderation, "describe_single_meme", new=AsyncMock(return_value="ok")),
        patch(
            "src.tgbot.service.get_meme_by_id",
            new=AsyncMock(return_value=refreshed),
        ),
        patch.object(
            moderation,
            "find_duplicate_by_ocr_text",
            new=AsyncMock(return_value=10000),
        ) as find_duplicate,
        patch.object(
            moderation,
            "resolve_duplicate",
            new=AsyncMock(
                return_value=SimpleNamespace(original_id=10000, reason="upload_ocr_text")
            ),
        ) as resolve_duplicate,
    ):
        refreshed_result, duplicate = await moderation._deduplicate_upload_via_ocr(meme)

    assert refreshed_result == refreshed
    assert duplicate is not None
    assert duplicate.duplicate_of == 10000
    find_duplicate.assert_awaited_once_with(10002, "same visible meme text")
    resolve_duplicate.assert_awaited_once_with(10002, 10000, reason="upload_ocr_text")
