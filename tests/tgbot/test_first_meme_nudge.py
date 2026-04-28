"""Tests for the first-meme nudge experiment (FFM-763)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from telegram.error import TelegramError
from tests.factories import create_user

from src.database import (
    engine,
    experiment_assignment,
    user,
)
from src.tgbot.senders.popups import (
    FIRST_MEME_NUDGE_EXPERIMENT_ID,
    FIRST_MEME_NUDGE_POPUP_ID,
    maybe_send_first_meme_nudge,
)
from src.tgbot.service import (
    create_user_popup_log,
    get_experiment_variant,
    user_popup_already_sent,
)

TREATMENT_USER_ID = 90100  # even -> treatment
CONTROL_USER_ID = 90101  # odd  -> control


@pytest_asyncio.fixture()
async def setup():
    async with engine.connect() as conn:
        await create_user(conn, id=TREATMENT_USER_ID)
        await create_user(conn, id=CONTROL_USER_ID)
        await conn.commit()

    yield

    async with engine.connect() as conn:
        # FK cascade clears popup logs + experiment assignments
        await conn.execute(user.delete().where(user.c.id.in_([TREATMENT_USER_ID, CONTROL_USER_ID])))
        await conn.commit()


def _user_info(lang: str = "en") -> dict:
    return {"interface_lang": lang, "nmemes_sent": 0}


def _mock_bot(send_message: AsyncMock | None = None) -> MagicMock:
    # python-telegram-bot 22 uses slotted descriptors on Bot, so the real
    # send_message attribute can't be replaced via setattr. Stub the whole bot
    # module reference instead with a MagicMock and attach the AsyncMock to it.
    mock_bot = MagicMock()
    mock_bot.send_message = send_message or AsyncMock()
    return mock_bot


@pytest.mark.asyncio
async def test_treatment_user_receives_nudge(setup):
    bot_mock = _mock_bot()
    with patch("src.tgbot.senders.popups.bot", bot_mock):
        await maybe_send_first_meme_nudge(TREATMENT_USER_ID, _user_info("en"))

    bot_mock.send_message.assert_called_once()
    call_kwargs = bot_mock.send_message.call_args.kwargs
    assert call_kwargs["chat_id"] == TREATMENT_USER_ID
    assert "❤️" in call_kwargs["text"]
    assert "⏬" in call_kwargs["text"]

    assert await user_popup_already_sent(TREATMENT_USER_ID, FIRST_MEME_NUDGE_POPUP_ID)
    assert (
        await get_experiment_variant(TREATMENT_USER_ID, FIRST_MEME_NUDGE_EXPERIMENT_ID)
        == "treatment"
    )


@pytest.mark.asyncio
async def test_control_user_assigned_but_not_messaged(setup):
    bot_mock = _mock_bot()
    with patch("src.tgbot.senders.popups.bot", bot_mock):
        await maybe_send_first_meme_nudge(CONTROL_USER_ID, _user_info("en"))

    bot_mock.send_message.assert_not_called()

    assert (
        await get_experiment_variant(CONTROL_USER_ID, FIRST_MEME_NUDGE_EXPERIMENT_ID) == "control"
    )
    # Control users do not get a popup log row — nothing was shown.
    assert not await user_popup_already_sent(CONTROL_USER_ID, FIRST_MEME_NUDGE_POPUP_ID)


@pytest.mark.asyncio
async def test_idempotent_treatment(setup):
    bot_mock = _mock_bot()
    with patch("src.tgbot.senders.popups.bot", bot_mock):
        await maybe_send_first_meme_nudge(TREATMENT_USER_ID, _user_info("en"))
        await maybe_send_first_meme_nudge(TREATMENT_USER_ID, _user_info("en"))

    bot_mock.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_concurrent_calls_send_only_once(setup):
    # Insert-first lease: even if both flows pass the pre-check, only the one
    # whose insert won the ON CONFLICT race is allowed to send.
    bot_mock = _mock_bot()
    with patch("src.tgbot.senders.popups.bot", bot_mock):
        await asyncio.gather(
            maybe_send_first_meme_nudge(TREATMENT_USER_ID, _user_info("en")),
            maybe_send_first_meme_nudge(TREATMENT_USER_ID, _user_info("en")),
        )

    assert bot_mock.send_message.call_count == 1


@pytest.mark.asyncio
async def test_send_failure_releases_lease(setup):
    # Transient TelegramError must roll back the popup-log row so the nudge
    # remains eligible to fire on a future attempt.
    failing_bot = _mock_bot(AsyncMock(side_effect=TelegramError("boom")))
    with patch("src.tgbot.senders.popups.bot", failing_bot):
        await maybe_send_first_meme_nudge(TREATMENT_USER_ID, _user_info("en"))

    assert not await user_popup_already_sent(TREATMENT_USER_ID, FIRST_MEME_NUDGE_POPUP_ID)

    # Next attempt should re-fire and succeed.
    ok_bot = _mock_bot()
    with patch("src.tgbot.senders.popups.bot", ok_bot):
        await maybe_send_first_meme_nudge(TREATMENT_USER_ID, _user_info("en"))

    ok_bot.send_message.assert_called_once()
    assert await user_popup_already_sent(TREATMENT_USER_ID, FIRST_MEME_NUDGE_POPUP_ID)


@pytest.mark.asyncio
async def test_existing_popup_log_short_circuits(setup):
    # Simulate a backfill / prior run that already logged the nudge.
    await create_user_popup_log(TREATMENT_USER_ID, FIRST_MEME_NUDGE_POPUP_ID)

    bot_mock = _mock_bot()
    with patch("src.tgbot.senders.popups.bot", bot_mock):
        await maybe_send_first_meme_nudge(TREATMENT_USER_ID, _user_info("en"))

    bot_mock.send_message.assert_not_called()
    # Pre-existing log path must not double-assign the experiment either.
    async with engine.connect() as conn:
        result = await conn.execute(
            select(experiment_assignment).where(
                experiment_assignment.c.user_id == TREATMENT_USER_ID,
                experiment_assignment.c.experiment_id == FIRST_MEME_NUDGE_EXPERIMENT_ID,
            )
        )
        assert result.first() is None


@pytest.mark.asyncio
async def test_russian_user_gets_localized_nudge(setup):
    bot_mock = _mock_bot()
    with patch("src.tgbot.senders.popups.bot", bot_mock):
        await maybe_send_first_meme_nudge(TREATMENT_USER_ID, _user_info("ru"))

    text = bot_mock.send_message.call_args.kwargs["text"]
    assert "Нажми" in text
    assert "❤️" in text
    assert "⏬" in text
