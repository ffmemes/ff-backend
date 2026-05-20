from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.storage.source_voting import (
    format_closed_poll_message,
    source_vote_should_reject_early,
)
from src.tgbot.constants import TELEGRAM_MODERATOR_CHAT_ID
from src.tgbot.handlers.moderator import source_candidates


def test_source_vote_should_reject_early_requires_age_zero_likes_and_six_dislikes():
    opened_at = datetime(2026, 5, 20, 10, 0, 0)
    poll = {"opened_at": opened_at}

    assert source_vote_should_reject_early(
        poll,
        {"yes": 0, "no": 6, "total": 6},
        opened_at + timedelta(minutes=90),
    )
    assert not source_vote_should_reject_early(
        poll,
        {"yes": 0, "no": 6, "total": 6},
        opened_at + timedelta(minutes=89),
    )
    assert not source_vote_should_reject_early(
        poll,
        {"yes": 1, "no": 6, "total": 7},
        opened_at + timedelta(hours=2),
    )
    assert not source_vote_should_reject_early(
        poll,
        {"yes": 0, "no": 5, "total": 5},
        opened_at + timedelta(hours=2),
    )


@pytest.mark.asyncio
async def test_handle_source_candidate_vote_early_rejects_and_posts_next_poll():
    query = SimpleNamespace(
        data="mscv:123:2",
        answer=AsyncMock(),
    )
    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=42),
        effective_chat=SimpleNamespace(id=TELEGRAM_MODERATOR_CHAT_ID),
    )
    context = SimpleNamespace(
        bot=SimpleNamespace(
            edit_message_text=AsyncMock(),
            unpin_chat_message=AsyncMock(),
        )
    )
    close_result = {
        "status": "rejected",
        "poll": {"chat_id": TELEGRAM_MODERATOR_CHAT_ID, "message_id": 123},
        "candidate": {"url": "https://t.me/ravememe", "times_forwarded": 12},
        "counts": {"yes": 0, "no": 6, "total": 6},
    }

    with (
        patch.object(
            source_candidates,
            "record_source_candidate_vote",
            new=AsyncMock(
                return_value={
                    "status": "early_rejected",
                    "close_result": close_result,
                }
            ),
        ),
        patch.object(
            source_candidates,
            "post_new_source_candidate_poll",
            new=AsyncMock(return_value={"status": "posted"}),
        ) as post_new_poll,
    ):
        await source_candidates.handle_source_candidate_vote(update, context)

    query.answer.assert_awaited_once_with("Источник отклонён, открываю следующий")
    context.bot.edit_message_text.assert_awaited_once_with(
        chat_id=TELEGRAM_MODERATOR_CHAT_ID,
        message_id=123,
        text=format_closed_poll_message(close_result),
        disable_web_page_preview=True,
    )
    context.bot.unpin_chat_message.assert_awaited_once_with(
        chat_id=TELEGRAM_MODERATOR_CHAT_ID,
        message_id=123,
    )
    post_new_poll.assert_awaited_once_with(context.bot)


def test_format_closed_poll_message_keeps_source_context_and_results():
    text = format_closed_poll_message(
        {
            "status": "rejected",
            "candidate": {"url": "https://t.me/ravememe", "times_forwarded": 12},
            "counts": {"yes": 0, "no": 6, "total": 6},
        }
    )

    assert "https://t.me/ravememe" in text
    assert "Наши паблики пересылали мемы оттуда 12 раз." in text
    assert "Голосование завершено: мем-источник отклонён." in text
    assert "Результаты голосования:" in text
    assert "За: 0" in text
    assert "Против: 6" in text
