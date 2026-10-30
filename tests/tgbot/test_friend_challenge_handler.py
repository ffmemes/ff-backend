"""Game flow with fake Telegram transport and a disposable database."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from telegram import User
from telegram.error import BadRequest
from tests.factories import create_meme, create_meme_source, create_user, create_user_language

from src.config import settings
from src.database import (
    engine,
    experiment_assignment,
    meme,
    meme_source,
    user,
    user_language,
    user_meme_reaction,
    user_tg,
)
from src.tgbot.handlers import friend_challenge as handler
from src.tgbot.handlers import start
from src.tgbot.repo import friend_challenge as repo

OWNER = 986001
GUEST = 986002
MEMES = list(range(986001, 986006))


def _update(user_id=GUEST, data=None, chat_type="private"):
    message = SimpleNamespace(reply_text=AsyncMock(), reply_video=AsyncMock())
    return SimpleNamespace(
        effective_user=User(
            id=user_id, is_bot=False, language_code="en", first_name="Test", is_premium=False
        ),
        effective_chat=SimpleNamespace(id=user_id, type=chat_type, send_message=AsyncMock()),
        message=message,
        effective_message=message,
        callback_query=SimpleNamespace(
            data=data, answer=AsyncMock(), edit_message_reply_markup=AsyncMock()
        )
        if data
        else None,
    )


@pytest_asyncio.fixture
async def game(monkeypatch):
    monkeypatch.setattr(settings, "FRIEND_CHALLENGE_ENABLED", True)
    info = {"id": GUEST, "type": "user", "interface_lang": "en", "nmemes_sent": 0}
    monkeypatch.setattr(handler, "get_user_info", AsyncMock(return_value=info))
    monkeypatch.setattr(handler, "update_user_info_cache", AsyncMock(return_value=info))
    monkeypatch.setattr(handler, "clear_meme_queue_for_user", AsyncMock())
    monkeypatch.setattr(handler, "next_message", AsyncMock())
    async with engine.begin() as conn:
        await conn.execute(delete(user).where(user.c.id.in_([OWNER, GUEST])))
        await conn.execute(delete(user_tg).where(user_tg.c.id == GUEST))
        await create_user(conn, OWNER)
        await create_user_language(conn, OWNER, "ru")
        await create_meme_source(conn, OWNER)
        for meme_id in MEMES:
            await create_meme(
                conn, meme_id, OWNER, caption="Caption retained", telegram_file_id=f"f{meme_id}"
            )
        await conn.execute(
            insert(experiment_assignment).values(
                experiment_id=repo.EXPERIMENT_ID, user_id=OWNER, variant=repo.TREATMENT
            )
        )
    pack = await repo.get_or_create_owner_pack(OWNER, MEMES)
    await repo.confirm_owner_pack(OWNER, pack["id"])
    yield pack, SimpleNamespace(bot=AsyncMock())
    async with engine.begin() as conn:
        await conn.execute(delete(user).where(user.c.id.in_([OWNER, GUEST])))
        await conn.execute(delete(user_tg).where(user_tg.c.id == GUEST))
        await conn.execute(delete(meme).where(meme.c.id.in_(MEMES)))
        await conn.execute(delete(meme_source).where(meme_source.c.id == OWNER))


async def _guest():
    async with engine.begin() as conn:
        await create_user(conn, GUEST)


async def test_five_answers_then_feed_seeds_answers(game):
    pack, context = game
    await _guest()
    await handler.handle_challenge_start(_update(), context, f"fc_{pack['token']}", created=False)
    assert context.bot.send_photo.await_count == 1
    assert "Caption retained" in context.bot.send_photo.call_args.kwargs["caption"]
    for position in range(1, 6):
        liked = int(position in {1, 3})
        await handler.handle_friend_callback(
            _update(data=f"fc:a:{pack['id']}:{position}:{liked}"), context
        )
    progress = await repo.get_progress(pack["id"], GUEST)
    assert progress["liked_count"] == 2 and progress["completed_at"] is not None
    assert context.bot.send_photo.await_count == 5
    assert "2 of" in context.bot.send_message.call_args.args[1]
    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    select(user_meme_reaction).where(user_meme_reaction.c.user_id == GUEST)
                )
            )
            .mappings()
            .all()
        )
    assert sorted(row["reaction_id"] for row in rows) == [1, 1, 2, 2, 2]
    assert {row["recommended_by"] for row in rows} == {"friend_challenge"}
    await handler.handle_friend_callback(_update(data=f"fc:feed:{pack['id']}"), context)
    assert handler.next_message.call_args.kwargs["skip_popups"] is True
    handler.clear_meme_queue_for_user.assert_awaited_with(GUEST)


async def test_repeat_answer_and_restart_resume_without_overwrite(game):
    pack, context = game
    await _guest()
    await handler.handle_challenge_start(_update(), context, f"fc_{pack['token']}", created=False)
    await handler.handle_friend_callback(_update(data=f"fc:a:{pack['id']}:1:1"), context)
    await handler.handle_friend_callback(_update(data=f"fc:a:{pack['id']}:1:0"), context)
    assert context.bot.send_photo.await_count == 2
    assert (await repo.get_progress(pack["id"], GUEST))["liked_count"] == 1
    await handler.handle_challenge_start(_update(), context, f"fc_{pack['token']}", created=False)
    assert "Meme 2 of 5" in context.bot.send_photo.call_args.kwargs["caption"]


async def test_transport_failure_keeps_answer_and_offers_resume(game):
    pack, context = game
    await _guest()
    await handler.handle_challenge_start(_update(), context, f"fc_{pack['token']}", created=False)
    context.bot.send_photo.side_effect = BadRequest("File unavailable")
    await handler.handle_friend_callback(_update(data=f"fc:a:{pack['id']}:1:1"), context)
    assert (await repo.get_progress(pack["id"], GUEST))["next_position"] == 2
    keyboard = context.bot.send_message.call_args.kwargs["reply_markup"]
    assert keyboard.inline_keyboard[0][0].callback_data == f"fc:resume:{pack['id']}"
    context.bot.send_photo.side_effect = None
    await handler.handle_friend_callback(_update(data=f"fc:resume:{pack['id']}"), context)
    assert "Meme 2 of 5" in context.bot.send_photo.call_args.kwargs["caption"]


async def test_self_start_and_unavailable_meme_never_create_progress(game):
    pack, context = game
    await _guest()
    await handler.handle_challenge_start(
        _update(OWNER), context, f"fc_{pack['token']}", created=False
    )
    assert await repo.get_progress(pack["id"], OWNER) is None
    context.bot.send_photo.assert_not_awaited()
    async with engine.begin() as conn:
        await conn.execute(update(meme).where(meme.c.id == MEMES[0]).values(status="rejected"))
    await handler.handle_challenge_start(_update(), context, f"fc_{pack['token']}", created=False)
    assert await repo.get_progress(pack["id"], GUEST) is None
    assert "unavailable" in context.bot.send_message.call_args.args[1]


async def test_group_callback_is_ignored(game):
    pack, context = game
    await _guest()
    await handler.handle_friend_callback(
        _update(data=f"fc:a:{pack['id']}:1:1", chat_type="group"), context
    )
    assert await repo.get_progress(pack["id"], GUEST) is None


async def test_offer_only_once_for_treatment(game, monkeypatch):
    _, context = game
    monkeypatch.setattr(repo.redis, "redis_client", AsyncMock(set=AsyncMock(return_value=True)))
    await handler.maybe_offer_challenge(context.bot, OWNER, MEMES[0], {"interface_lang": "en"})
    await handler.maybe_offer_challenge(context.bot, OWNER, MEMES[0], {"interface_lang": "en"})
    assert context.bot.send_message.await_count == 1
    assignment = await repo.get_or_assign_variant(OWNER)
    assert "offered_at" in assignment["assignment_metadata"]


async def test_owner_creates_previews_and_confirms(game):
    _, context = game
    async with engine.begin() as conn:
        await conn.execute(delete(user).where(user.c.id == OWNER))
        await create_user(conn, OWNER)
        await create_user_language(conn, OWNER, "ru")
        await conn.execute(
            insert(experiment_assignment).values(
                experiment_id=repo.EXPERIMENT_ID, user_id=OWNER, variant=repo.TREATMENT
            )
        )
        for meme_id in MEMES:
            await conn.execute(
                insert(user_meme_reaction).values(
                    user_id=OWNER, meme_id=meme_id, recommended_by="test", reaction_id=1
                )
            )
    await handler.handle_friend_callback(_update(OWNER, data="fc:create"), context)
    assert context.bot.send_photo.await_count == 5
    confirm = context.bot.send_message.call_args.kwargs["reply_markup"].inline_keyboard[0][0]
    await handler.handle_friend_callback(_update(OWNER, data=confirm.callback_data), context)
    pack = await repo.get_owner_pack(OWNER)
    assert pack["confirmed_at"] is not None
    assert f"fc_{pack['token']}" in context.bot.send_message.call_args.args[1]


@pytest.mark.parametrize("payload", [None, "fc_", "fc_1", "fc_" + "a" * 25, "m_1_2"])
def test_invalid_tokens(payload):
    assert handler.parse_challenge_token(payload) is None


# --- real /start routing ---


@pytest.fixture
def start_fakes(monkeypatch, game):
    info = {"id": GUEST, "type": "user", "interface_lang": "en", "nmemes_sent": 0}
    monkeypatch.setattr(start, "update_user_info_cache", AsyncMock(return_value=info))
    for name in (
        "log_start_event",
        "handle_invited_user",
        "handle_shared_meme_reward",
        "onboarding_flow",
        "send_onboarding_language_picker",
        "next_message",
    ):
        monkeypatch.setattr(start, name, AsyncMock())
    return game


async def test_new_user_start_shows_first_meme_and_sets_inviter(start_fakes):
    pack, context = start_fakes
    context.args = [f"fc_{pack['token']}"]
    await start.handle_start(_update(), context)

    progress = await repo.get_progress(pack["id"], GUEST)
    assert progress["answered_count"] == 0
    assert "Meme 1 of 5" in context.bot.send_photo.call_args.kwargs["caption"]
    async with engine.connect() as conn:
        inviter = (
            await conn.execute(select(user.c.inviter_id).where(user.c.id == GUEST))
        ).scalar_one()
        languages = (
            await conn.execute(
                select(user_language.c.language_code).where(user_language.c.user_id == GUEST)
            )
        ).scalars()
        assert set(languages) == {"ru"}
    assert inviter == OWNER
    start.onboarding_flow.assert_not_awaited()
    start.send_onboarding_language_picker.assert_not_awaited()


async def test_flag_off_start_uses_normal_onboarding(start_fakes, monkeypatch):
    pack, context = start_fakes
    monkeypatch.setattr(settings, "FRIEND_CHALLENGE_ENABLED", False)
    context.args = [f"fc_{pack['token']}"]
    await start.handle_start(_update(), context)
    assert await repo.get_progress(pack["id"], GUEST) is None
    context.bot.send_photo.assert_not_awaited()
