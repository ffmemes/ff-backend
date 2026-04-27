"""Tests for the first-meme nudge experiment (FFM-763)."""

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
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


@pytest.mark.asyncio
@patch("src.tgbot.senders.popups.bot.send_message", new_callable=AsyncMock)
async def test_treatment_user_receives_nudge(mock_send, setup):
    await maybe_send_first_meme_nudge(TREATMENT_USER_ID, _user_info("en"))

    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args.kwargs
    assert call_kwargs["chat_id"] == TREATMENT_USER_ID
    assert "👍" in call_kwargs["text"]

    assert await user_popup_already_sent(TREATMENT_USER_ID, FIRST_MEME_NUDGE_POPUP_ID)
    assert (
        await get_experiment_variant(TREATMENT_USER_ID, FIRST_MEME_NUDGE_EXPERIMENT_ID)
        == "treatment"
    )


@pytest.mark.asyncio
@patch("src.tgbot.senders.popups.bot.send_message", new_callable=AsyncMock)
async def test_control_user_assigned_but_not_messaged(mock_send, setup):
    await maybe_send_first_meme_nudge(CONTROL_USER_ID, _user_info("en"))

    mock_send.assert_not_called()

    assert (
        await get_experiment_variant(CONTROL_USER_ID, FIRST_MEME_NUDGE_EXPERIMENT_ID) == "control"
    )
    # Control users do not get a popup log row — nothing was shown.
    assert not await user_popup_already_sent(CONTROL_USER_ID, FIRST_MEME_NUDGE_POPUP_ID)


@pytest.mark.asyncio
@patch("src.tgbot.senders.popups.bot.send_message", new_callable=AsyncMock)
async def test_idempotent_treatment(mock_send, setup):
    await maybe_send_first_meme_nudge(TREATMENT_USER_ID, _user_info("en"))
    await maybe_send_first_meme_nudge(TREATMENT_USER_ID, _user_info("en"))

    mock_send.assert_called_once()


@pytest.mark.asyncio
@patch("src.tgbot.senders.popups.bot.send_message", new_callable=AsyncMock)
async def test_existing_popup_log_short_circuits(mock_send, setup):
    # Simulate a backfill / prior run that already logged the nudge.
    await create_user_popup_log(TREATMENT_USER_ID, FIRST_MEME_NUDGE_POPUP_ID)

    await maybe_send_first_meme_nudge(TREATMENT_USER_ID, _user_info("en"))

    mock_send.assert_not_called()
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
@patch("src.tgbot.senders.popups.bot.send_message", new_callable=AsyncMock)
async def test_russian_user_gets_localized_nudge(mock_send, setup):
    await maybe_send_first_meme_nudge(TREATMENT_USER_ID, _user_info("ru"))

    text = mock_send.call_args.kwargs["text"]
    assert "Нажми" in text
