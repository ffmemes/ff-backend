from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.constants import ReactionEmoji
from telegram.error import BadRequest

from src.tgbot.handlers.chat import reaction as reaction_handler


def _make_update(set_reaction: AsyncMock) -> SimpleNamespace:
    return SimpleNamespace(message=SimpleNamespace(set_reaction=set_reaction))


@pytest.mark.asyncio
async def test_give_random_reaction_uses_only_supported_standard_reactions(monkeypatch):
    set_reaction = AsyncMock()
    update = _make_update(set_reaction)

    monkeypatch.setattr(reaction_handler.random, "random", lambda: 0)
    monkeypatch.setattr(reaction_handler.random, "choice", lambda reactions: reactions[0])
    monkeypatch.setattr(reaction_handler.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(reaction_handler, "MESSAGE_REACTIONS", ("not-a-custom-emoji-id",))
    monkeypatch.setattr(reaction_handler, "SUPPORTED_MESSAGE_REACTIONS", ("👍",))

    await reaction_handler.give_random_reaction(update, SimpleNamespace())

    set_reaction.assert_awaited_once_with(reaction="👍", is_big=True)


@pytest.mark.asyncio
async def test_give_random_reaction_skips_badrequest_from_telegram(monkeypatch):
    set_reaction = AsyncMock(
        side_effect=BadRequest(
            'Can\'t parse reactiontype: field "custom_emoji_id" must be a valid number'
        )
    )
    update = _make_update(set_reaction)

    monkeypatch.setattr(reaction_handler.random, "random", lambda: 0)
    monkeypatch.setattr(reaction_handler.random, "choice", lambda reactions: reactions[0])
    monkeypatch.setattr(reaction_handler.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(reaction_handler, "SUPPORTED_MESSAGE_REACTIONS", ("👍",))

    await reaction_handler.give_random_reaction(update, SimpleNamespace())

    set_reaction.assert_awaited_once_with(reaction="👍", is_big=True)


def test_supported_message_reactions_are_standard_telegram_reactions():
    assert reaction_handler.SUPPORTED_MESSAGE_REACTIONS
    assert set(reaction_handler.SUPPORTED_MESSAGE_REACTIONS) <= set(ReactionEmoji)
