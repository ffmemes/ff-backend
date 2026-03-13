"""Handler orchestration tests for handle_reaction()."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from tests.factories import (
    cleanup_test_data,
    create_meme,
    create_meme_source,
    create_user,
    create_user_language,
    create_user_stats,
)

from src.database import engine
from src.recommendations.service import create_user_meme_reaction


@pytest_asyncio.fixture(loop_scope="session")
async def setup():
    async with engine.connect() as conn:
        await create_user(conn, id=10001)
        await create_user_language(conn, user_id=10001)
        await create_user_stats(conn, user_id=10001, nmemes_sent=50)
        await create_meme_source(conn, id=10001)
        await create_meme(conn, id=10001, meme_source_id=10001)
        await create_meme(conn, id=10002, meme_source_id=10001)
        await conn.commit()

    yield

    async with engine.connect() as conn:
        await cleanup_test_data(conn)


def _make_update(meme_id: int, reaction_id: int, user_id: int = 10001):
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        callback_query=SimpleNamespace(
            data=f"r:{meme_id}:{reaction_id}",
            message=SimpleNamespace(message_id=999, chat=SimpleNamespace(id=user_id)),
        ),
    )


def _make_context():
    return SimpleNamespace(bot=AsyncMock())


HANDLER_MODULE = "src.tgbot.handlers.reaction"


@pytest.mark.asyncio
@patch(f"{HANDLER_MODULE}.next_message", new_callable=AsyncMock)
@patch(f"{HANDLER_MODULE}.reward_user_for_daily_activity", new_callable=AsyncMock)
@patch(f"{HANDLER_MODULE}.update_user_last_active_at", new_callable=AsyncMock)
@patch(f"{HANDLER_MODULE}.maybe_send_moderator_invite", new_callable=AsyncMock)
@patch(f"{HANDLER_MODULE}.update_user_info_counters", new_callable=AsyncMock)
async def test_new_reaction_calls_next_message(
    mock_counters, mock_mod_invite, mock_active, mock_reward, mock_next, setup
):
    from src.tgbot.handlers.reaction import handle_reaction

    # Pre-create the reaction row with NULL reaction_id
    await create_user_meme_reaction(10001, 10001, "test")
    mock_counters.return_value = {"nmemes_sent": 51, "memes_watched_today": 1}

    update = _make_update(meme_id=10001, reaction_id=1)
    context = _make_context()
    await handle_reaction(update, context)

    mock_next.assert_called_once()


@pytest.mark.asyncio
@patch(f"{HANDLER_MODULE}.next_message", new_callable=AsyncMock)
@patch(f"{HANDLER_MODULE}.reward_user_for_daily_activity", new_callable=AsyncMock)
@patch(f"{HANDLER_MODULE}.update_user_last_active_at", new_callable=AsyncMock)
@patch(f"{HANDLER_MODULE}.maybe_send_moderator_invite", new_callable=AsyncMock)
@patch(f"{HANDLER_MODULE}.update_user_info_counters", new_callable=AsyncMock)
async def test_duplicate_reaction_skips_next_message(
    mock_counters, mock_mod_invite, mock_active, mock_reward, mock_next, setup
):
    from src.tgbot.handlers.reaction import handle_reaction

    await create_user_meme_reaction(10001, 10001, "test")
    mock_counters.return_value = {"nmemes_sent": 51, "memes_watched_today": 1}

    update = _make_update(meme_id=10001, reaction_id=1)
    context = _make_context()

    # First reaction
    await handle_reaction(update, context)
    # Second identical reaction
    await handle_reaction(update, context)

    assert mock_next.call_count == 1


@pytest.mark.asyncio
@patch(f"{HANDLER_MODULE}.next_message", new_callable=AsyncMock)
@patch(f"{HANDLER_MODULE}.reward_user_for_daily_activity", new_callable=AsyncMock)
@patch(f"{HANDLER_MODULE}.update_user_last_active_at", new_callable=AsyncMock)
@patch(f"{HANDLER_MODULE}.maybe_send_moderator_invite", new_callable=AsyncMock)
@patch(f"{HANDLER_MODULE}.update_user_info_counters", new_callable=AsyncMock)
async def test_calls_update_user_info_counters(
    mock_counters, mock_mod_invite, mock_active, mock_reward, mock_next, setup
):
    from src.tgbot.handlers.reaction import handle_reaction

    await create_user_meme_reaction(10001, 10001, "test")
    mock_counters.return_value = {"nmemes_sent": 51, "memes_watched_today": 1}

    update = _make_update(meme_id=10001, reaction_id=1)
    context = _make_context()
    await handle_reaction(update, context)

    mock_counters.assert_called_once_with(10001)


@pytest.mark.asyncio
@patch(f"{HANDLER_MODULE}.next_message", new_callable=AsyncMock)
@patch(f"{HANDLER_MODULE}.reward_user_for_daily_activity", new_callable=AsyncMock)
@patch(f"{HANDLER_MODULE}.update_user_last_active_at", new_callable=AsyncMock)
@patch(f"{HANDLER_MODULE}.maybe_send_moderator_invite", new_callable=AsyncMock)
@patch(f"{HANDLER_MODULE}.update_user_info_counters", new_callable=AsyncMock)
async def test_calls_moderator_invite_check(
    mock_counters, mock_mod_invite, mock_active, mock_reward, mock_next, setup
):
    from src.tgbot.handlers.reaction import handle_reaction

    await create_user_meme_reaction(10001, 10001, "test")
    mock_counters.return_value = {"nmemes_sent": 51, "memes_watched_today": 1}

    update = _make_update(meme_id=10001, reaction_id=1)
    context = _make_context()
    await handle_reaction(update, context)

    mock_mod_invite.assert_called_once()


@pytest.mark.asyncio
@patch(f"{HANDLER_MODULE}.next_message", new_callable=AsyncMock)
@patch(f"{HANDLER_MODULE}.reward_user_for_daily_activity", new_callable=AsyncMock)
@patch(f"{HANDLER_MODULE}.update_user_last_active_at", new_callable=AsyncMock)
@patch(f"{HANDLER_MODULE}.maybe_send_moderator_invite", new_callable=AsyncMock)
@patch(f"{HANDLER_MODULE}.update_user_info_counters", new_callable=AsyncMock)
async def test_reaction_persisted_in_db(
    mock_counters, mock_mod_invite, mock_active, mock_reward, mock_next, setup
):
    from sqlalchemy import select

    from src.database import user_meme_reaction
    from src.tgbot.handlers.reaction import handle_reaction

    await create_user_meme_reaction(10001, 10002, "test")
    mock_counters.return_value = {"nmemes_sent": 51, "memes_watched_today": 1}

    update = _make_update(meme_id=10002, reaction_id=2)
    context = _make_context()
    await handle_reaction(update, context)

    async with engine.connect() as conn:
        row = await conn.execute(
            select(user_meme_reaction).where(
                user_meme_reaction.c.user_id == 10001,
                user_meme_reaction.c.meme_id == 10002,
            )
        )
        result = row.first()._asdict()

    assert result["reaction_id"] == 2
    assert result["reacted_at"] is not None


@pytest.mark.asyncio
@patch(f"{HANDLER_MODULE}.next_message", new_callable=AsyncMock)
@patch(f"{HANDLER_MODULE}.reward_user_for_daily_activity", new_callable=AsyncMock)
@patch(f"{HANDLER_MODULE}.update_user_last_active_at", new_callable=AsyncMock)
@patch(f"{HANDLER_MODULE}.maybe_send_moderator_invite", new_callable=AsyncMock)
@patch(f"{HANDLER_MODULE}.update_user_info_counters", new_callable=AsyncMock)
async def test_passes_reaction_id_to_next_message(
    mock_counters, mock_mod_invite, mock_active, mock_reward, mock_next, setup
):
    from src.tgbot.handlers.reaction import handle_reaction

    await create_user_meme_reaction(10001, 10001, "test")
    mock_counters.return_value = {"nmemes_sent": 51, "memes_watched_today": 1}

    update = _make_update(meme_id=10001, reaction_id=2)
    context = _make_context()
    await handle_reaction(update, context)

    call_kwargs = mock_next.call_args
    prev_id = call_kwargs.kwargs.get("prev_reaction_id")
    if prev_id is None:
        prev_id = call_kwargs[1].get("prev_reaction_id")
    assert prev_id == 2
