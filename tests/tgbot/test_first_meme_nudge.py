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
from src.tgbot.senders import popups
from src.tgbot.senders.popups import (
    FIRST_MEME_NUDGE_EXPERIMENT_ID,
    FIRST_MEME_NUDGE_POPUP_ID,
    get_first_meme_nudge_variant_to_send,
    get_or_assign_first_meme_nudge_variant,
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
    variant = await get_or_assign_first_meme_nudge_variant(TREATMENT_USER_ID)
    assert variant == "treatment"

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
    variant = await get_or_assign_first_meme_nudge_variant(CONTROL_USER_ID)
    assert variant == "control"

    bot_mock = _mock_bot()
    with patch("src.tgbot.senders.popups.bot", bot_mock):
        # Even if dispatched (it shouldn't be — caller gates on variant), the
        # sender must no-op for control to keep accidental traffic off Telegram.
        await maybe_send_first_meme_nudge(CONTROL_USER_ID, _user_info("en"))

    bot_mock.send_message.assert_not_called()

    assert (
        await get_experiment_variant(CONTROL_USER_ID, FIRST_MEME_NUDGE_EXPERIMENT_ID) == "control"
    )
    # Control users do not get a popup log row — nothing was shown.
    assert not await user_popup_already_sent(CONTROL_USER_ID, FIRST_MEME_NUDGE_POPUP_ID)


@pytest.mark.asyncio
async def test_idempotent_treatment(setup):
    await get_or_assign_first_meme_nudge_variant(TREATMENT_USER_ID)

    bot_mock = _mock_bot()
    with patch("src.tgbot.senders.popups.bot", bot_mock):
        await maybe_send_first_meme_nudge(TREATMENT_USER_ID, _user_info("en"))
        await maybe_send_first_meme_nudge(TREATMENT_USER_ID, _user_info("en"))

    bot_mock.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_concurrent_calls_send_only_once(setup):
    # Insert-first lease: even if both flows pass the pre-check, only the one
    # whose insert won the ON CONFLICT race is allowed to send.
    await get_or_assign_first_meme_nudge_variant(TREATMENT_USER_ID)

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
    await get_or_assign_first_meme_nudge_variant(TREATMENT_USER_ID)

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
async def test_send_cancellation_releases_lease(monkeypatch):
    delete_user_popup_log = AsyncMock()
    monkeypatch.setattr(popups, "get_experiment_variant", AsyncMock(return_value="treatment"))
    monkeypatch.setattr(popups, "create_user_popup_log", AsyncMock(return_value=True))
    monkeypatch.setattr(popups, "delete_user_popup_log", delete_user_popup_log)

    cancelled_bot = _mock_bot(AsyncMock(side_effect=asyncio.CancelledError))
    monkeypatch.setattr(popups, "bot", cancelled_bot)

    with pytest.raises(asyncio.CancelledError):
        await maybe_send_first_meme_nudge(TREATMENT_USER_ID, _user_info("en"))

    delete_user_popup_log.assert_awaited_once_with(TREATMENT_USER_ID, FIRST_MEME_NUDGE_POPUP_ID)


@pytest.mark.asyncio
async def test_existing_popup_log_short_circuits(setup):
    # Simulate a backfill / prior run that already logged the nudge.
    await create_user_popup_log(TREATMENT_USER_ID, FIRST_MEME_NUDGE_POPUP_ID)

    variant = await get_or_assign_first_meme_nudge_variant(TREATMENT_USER_ID)
    assert variant is None  # short-circuit: no further action

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
    await get_or_assign_first_meme_nudge_variant(TREATMENT_USER_ID)

    bot_mock = _mock_bot()
    with patch("src.tgbot.senders.popups.bot", bot_mock):
        await maybe_send_first_meme_nudge(TREATMENT_USER_ID, _user_info("ru"))

    text = bot_mock.send_message.call_args.kwargs["text"]
    assert "Нажми" in text
    assert "❤️" in text
    assert "⏬" in text


@pytest.mark.asyncio
async def test_assignment_helper_is_idempotent(setup):
    # Re-entrant calls (e.g. /start retries before the first reaction lands)
    # must NOT re-emit `evaluated` or duplicate the assignment row.
    first = await get_or_assign_first_meme_nudge_variant(CONTROL_USER_ID)
    second = await get_or_assign_first_meme_nudge_variant(CONTROL_USER_ID)

    assert first == "control"
    assert second == "control"

    async with engine.connect() as conn:
        result = await conn.execute(
            select(experiment_assignment).where(
                experiment_assignment.c.user_id == CONTROL_USER_ID,
                experiment_assignment.c.experiment_id == FIRST_MEME_NUDGE_EXPERIMENT_ID,
            )
        )
        rows = result.fetchall()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_delivery_helper_retries_only_existing_treatment_assignment(monkeypatch):
    assign_variant = AsyncMock(return_value="treatment")
    popup_sent = AsyncMock(return_value=False)
    get_variant = AsyncMock(return_value=None)
    monkeypatch.setattr(popups, "get_or_assign_first_meme_nudge_variant", assign_variant)
    monkeypatch.setattr(popups, "user_popup_already_sent", popup_sent)
    monkeypatch.setattr(popups, "get_experiment_variant", get_variant)

    assert (
        await get_first_meme_nudge_variant_to_send(TREATMENT_USER_ID, is_first_meme=True)
        == "treatment"
    )
    assign_variant.assert_awaited_once_with(TREATMENT_USER_ID)

    assert await get_first_meme_nudge_variant_to_send(CONTROL_USER_ID, is_first_meme=False) is None
    assign_variant.assert_awaited_once()
    get_variant.assert_awaited_once_with(CONTROL_USER_ID, FIRST_MEME_NUDGE_EXPERIMENT_ID)

    get_variant.return_value = "treatment"
    assert (
        await get_first_meme_nudge_variant_to_send(TREATMENT_USER_ID, is_first_meme=False)
        == "treatment"
    )

    popup_sent.return_value = True
    assert (
        await get_first_meme_nudge_variant_to_send(TREATMENT_USER_ID, is_first_meme=False) is None
    )


@pytest.mark.asyncio
async def test_sender_no_ops_without_assignment(setup):
    # Defensive: if the sender ever fires without the sync helper having run
    # (e.g. a future caller forgets to gate on variant), it must not send.
    bot_mock = _mock_bot()
    with patch("src.tgbot.senders.popups.bot", bot_mock):
        await maybe_send_first_meme_nudge(TREATMENT_USER_ID, _user_info("en"))

    bot_mock.send_message.assert_not_called()
    assert not await user_popup_already_sent(TREATMENT_USER_ID, FIRST_MEME_NUDGE_POPUP_ID)
