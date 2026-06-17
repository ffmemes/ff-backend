"""Regression coverage for handle_start side effects (FFM-907).

Asserts that every onboarding side effect fires for `created=True`
users on every deep_link branch — kitchen used to silently skip
`init_user_languages_from_tg_user` (PR #222 fix), and we want a test
guarding against a future branch dropping the same call again.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from telegram import User
from telegram.ext import ContextTypes
from tests.factories import create_meme, create_meme_source, create_reaction

from src.database import (
    engine,
    meme,
    meme_source,
    user,
    user_deep_link_log,
    user_language,
    user_meme_reaction,
    user_tg,
)

NEW_USER_ID = 90201
EXISTING_USER_ID = 90202


def _make_tg_user(user_id: int = NEW_USER_ID) -> User:
    # Real telegram.User so init_user_languages_from_tg_user can read
    # full_name/language_code/id without us mocking the Cyrillic detection.
    return User(
        id=user_id,
        first_name="Test",
        last_name="User",
        is_bot=False,
        username=f"u{user_id}",
        language_code="en",
        is_premium=False,
    )


def _make_update(deep_link: str | None = None, user_id: int = NEW_USER_ID):
    return SimpleNamespace(
        effective_user=_make_tg_user(user_id),
        message=SimpleNamespace(reply_text=AsyncMock(), reply_video=AsyncMock()),
        callback_query=None,
        effective_chat=SimpleNamespace(send_message=AsyncMock()),
    )


def _make_context(deep_link: str | None) -> ContextTypes.DEFAULT_TYPE:
    args = [deep_link] if deep_link else []
    return SimpleNamespace(args=args, bot=AsyncMock())


async def _cleanup_user(user_id: int) -> None:
    async with engine.connect() as conn:
        await conn.execute(
            delete(user_deep_link_log).where(user_deep_link_log.c.user_id == user_id)
        )
        await conn.execute(
            delete(user_meme_reaction).where(user_meme_reaction.c.user_id == user_id)
        )
        await conn.execute(delete(user_language).where(user_language.c.user_id == user_id))
        await conn.execute(delete(user).where(user.c.id == user_id))
        await conn.execute(delete(user_tg).where(user_tg.c.id == user_id))
        await conn.commit()


async def _cleanup_shared_meme_fixture() -> None:
    async with engine.connect() as conn:
        await conn.execute(delete(user_meme_reaction).where(user_meme_reaction.c.meme_id == 10001))
        await conn.execute(delete(meme).where(meme.c.id == 10001))
        await conn.execute(delete(meme_source).where(meme_source.c.id == 10001))
        await conn.commit()


@pytest_asyncio.fixture()
async def cleanup():
    await _cleanup_shared_meme_fixture()
    await _cleanup_user(NEW_USER_ID)
    await _cleanup_user(EXISTING_USER_ID)
    yield
    await _cleanup_shared_meme_fixture()
    await _cleanup_user(NEW_USER_ID)
    await _cleanup_user(EXISTING_USER_ID)


HANDLER_MODULE = "src.tgbot.handlers.start"


def _patch_handlers(shared_meme_sent: bool = False):
    """Patch every downstream handler so we test orchestration only."""
    return [
        patch(f"{HANDLER_MODULE}.handle_show_kitchen", new_callable=AsyncMock),
        patch(f"{HANDLER_MODULE}.handle_language_settings", new_callable=AsyncMock),
        patch(f"{HANDLER_MODULE}.handle_invited_user", new_callable=AsyncMock),
        patch(f"{HANDLER_MODULE}.handle_shared_meme_reward", new_callable=AsyncMock),
        patch(
            f"{HANDLER_MODULE}._send_shared_meme_from_deep_link",
            new_callable=AsyncMock,
            return_value=shared_meme_sent,
        ),
        patch(f"{HANDLER_MODULE}.onboarding_flow", new_callable=AsyncMock),
        patch(f"{HANDLER_MODULE}.next_message", new_callable=AsyncMock),
        patch(f"{HANDLER_MODULE}.log_start_event", new_callable=AsyncMock),
        patch("src.tgbot.handlers.stats.wrapped.handle_wrapped", new_callable=AsyncMock),
        patch(
            "src.tgbot.handlers.treasury.giveaway.handle_giveaway",
            new_callable=AsyncMock,
        ),
    ]


async def _assert_universal_side_effects(user_id: int, expected_deep_link: str | None) -> None:
    """Side effects every /start MUST run for created=True, all branches."""
    async with engine.connect() as conn:
        tg_row = (await conn.execute(select(user_tg).where(user_tg.c.id == user_id))).first()
        u_row = (await conn.execute(select(user).where(user.c.id == user_id))).first()
        lang_rows = (
            await conn.execute(select(user_language).where(user_language.c.user_id == user_id))
        ).fetchall()
        dl_rows = (
            await conn.execute(
                select(user_deep_link_log).where(user_deep_link_log.c.user_id == user_id)
            )
        ).fetchall()

    assert tg_row is not None, "user_tg row missing"
    assert u_row is not None, "user row missing"
    assert len(lang_rows) >= 1, "user_language rows missing — onboarding leak!"
    assert len(dl_rows) == 1, "user_deep_link_log row missing"
    assert dl_rows[0]._asdict()["deep_link"] == expected_deep_link


async def _run_handle_start(
    deep_link: str | None,
    user_id: int = NEW_USER_ID,
    shared_meme_sent: bool = False,
):
    from src.tgbot.handlers.start import handle_start

    update = _make_update(deep_link, user_id)
    context = _make_context(deep_link)

    patches = _patch_handlers(shared_meme_sent=shared_meme_sent)
    started = [p.start() for p in patches]
    try:
        await handle_start(update, context)
    finally:
        for p in patches:
            p.stop()
    return dict(
        zip(
            [
                "kitchen",
                "lang_settings",
                "invited",
                "shared_reward",
                "shared_meme",
                "onboarding",
                "next_message",
                "log_start",
                "wrapped",
                "giveaway",
            ],
            started,
        )
    )


@pytest.mark.asyncio
async def test_new_user_no_deep_link_enters_onboarding_without_db():
    from src.tgbot.handlers.start import handle_start

    update = _make_update(deep_link=None)
    context = _make_context(deep_link=None)

    with (
        patch(f"{HANDLER_MODULE}.save_user_data", new_callable=AsyncMock) as save_user,
        patch(f"{HANDLER_MODULE}.update_user_info_cache", new_callable=AsyncMock) as user_info,
        patch(f"{HANDLER_MODULE}.log_user_deep_link", new_callable=AsyncMock),
        patch(f"{HANDLER_MODULE}.log_start_event", new_callable=AsyncMock),
        patch(f"{HANDLER_MODULE}.get_user_languages", new_callable=AsyncMock) as languages,
        patch(
            f"{HANDLER_MODULE}._send_shared_meme_from_deep_link",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(f"{HANDLER_MODULE}.handle_invited_user", new_callable=AsyncMock),
        patch(f"{HANDLER_MODULE}.handle_language_settings", new_callable=AsyncMock) as settings,
        patch(f"{HANDLER_MODULE}.onboarding_flow", new_callable=AsyncMock) as onboarding,
    ):
        save_user.return_value = ({"id": NEW_USER_ID}, True)
        user_info.return_value = {"type": "user", "interface_lang": "en"}
        languages.return_value = {"en"}

        await handle_start(update, context)

    settings.assert_awaited_once_with(update, context)
    onboarding.assert_awaited_once_with(update, context.bot)


@pytest.mark.asyncio
async def test_new_user_no_deep_link_runs_universal_side_effects(cleanup):
    mocks = await _run_handle_start(deep_link=None)
    await _assert_universal_side_effects(NEW_USER_ID, expected_deep_link=None)
    mocks["lang_settings"].assert_called_once()
    mocks["invited"].assert_called_once()
    mocks["onboarding"].assert_called_once()
    mocks["next_message"].assert_not_called()
    mocks["kitchen"].assert_not_called()
    mocks["wrapped"].assert_not_called()
    mocks["giveaway"].assert_not_called()


@pytest.mark.asyncio
async def test_new_user_kitchen_branch_still_inits_languages(cleanup):
    """The exact regression that broke Sega — kitchen used to skip init."""
    mocks = await _run_handle_start(deep_link="kitchen")
    await _assert_universal_side_effects(NEW_USER_ID, expected_deep_link="kitchen")
    mocks["kitchen"].assert_called_once()
    mocks["lang_settings"].assert_not_called()
    mocks["onboarding"].assert_not_called()
    mocks["next_message"].assert_not_called()


@pytest.mark.asyncio
async def test_new_user_wrapped_branch_inits_languages(cleanup):
    mocks = await _run_handle_start(deep_link="wrapped")
    await _assert_universal_side_effects(NEW_USER_ID, expected_deep_link="wrapped")
    mocks["wrapped"].assert_called_once()
    mocks["lang_settings"].assert_not_called()
    mocks["onboarding"].assert_not_called()


@pytest.mark.asyncio
async def test_new_user_giveaway_branch_inits_languages(cleanup):
    mocks = await _run_handle_start(deep_link="giveaway_77")
    await _assert_universal_side_effects(NEW_USER_ID, expected_deep_link="giveaway_77")
    mocks["lang_settings"].assert_called_once()  # main `created` path runs
    mocks["giveaway"].assert_called_once()
    mocks["onboarding"].assert_called_once()


@pytest.mark.asyncio
async def test_new_user_share_link_branch_inits_languages(cleanup):
    mocks = await _run_handle_start(deep_link="m_12345_678", shared_meme_sent=True)
    await _assert_universal_side_effects(NEW_USER_ID, expected_deep_link="m_12345_678")
    mocks["shared_meme"].assert_called_once()
    assert mocks["shared_meme"].call_args.kwargs["reaction_context"] == "onboard"
    mocks["lang_settings"].assert_not_called()
    mocks["onboarding"].assert_not_called()
    mocks["invited"].assert_called_once()


@pytest.mark.asyncio
async def test_blocked_acquisition_channel_silently_drops_new_user(cleanup):
    """Blocked acquisition channels: no user row created at all (by design)."""
    mocks = await _run_handle_start(deep_link="likefollowbot")

    async with engine.connect() as conn:
        u_row = (await conn.execute(select(user).where(user.c.id == NEW_USER_ID))).first()
        tg_row = (await conn.execute(select(user_tg).where(user_tg.c.id == NEW_USER_ID))).first()

    assert u_row is None, "blocked channel should not create user row"
    assert tg_row is None, "blocked channel should not create user_tg row"
    mocks["lang_settings"].assert_not_called()
    mocks["onboarding"].assert_not_called()
    mocks["next_message"].assert_not_called()
    mocks["log_start"].assert_not_called()


@pytest.mark.asyncio
async def test_existing_user_no_deep_link_serves_meme(cleanup):
    """Existing-user branch: must call next_message (the meme)."""
    # First /start: bootstraps the user.
    await _run_handle_start(deep_link=None, user_id=EXISTING_USER_ID)
    await _assert_universal_side_effects(EXISTING_USER_ID, expected_deep_link=None)

    # Second /start: same user → existing-user branch.
    mocks = await _run_handle_start(deep_link=None, user_id=EXISTING_USER_ID)
    mocks["next_message"].assert_called_once()
    mocks["lang_settings"].assert_not_called()


@pytest.mark.asyncio
async def test_existing_user_share_link_serves_shared_meme(cleanup):
    await _run_handle_start(deep_link=None, user_id=EXISTING_USER_ID)

    mocks = await _run_handle_start(
        deep_link="m_12345_678",
        user_id=EXISTING_USER_ID,
        shared_meme_sent=True,
    )

    mocks["shared_meme"].assert_called_once()
    mocks["shared_reward"].assert_called_once()
    mocks["onboarding"].assert_not_called()
    mocks["next_message"].assert_not_called()
    mocks["lang_settings"].assert_not_called()


@pytest.mark.asyncio
async def test_existing_user_share_link_with_prior_reaction_serves_shared_meme(cleanup):
    from src.tgbot.handlers.start import handle_start

    await _run_handle_start(deep_link=None, user_id=EXISTING_USER_ID)
    async with engine.begin() as conn:
        await create_meme_source(conn, id=10001, language_code="en")
        await create_meme(
            conn,
            id=10001,
            meme_source_id=10001,
            language_code="en",
            telegram_file_id="test_shared_file_id",
        )
        await create_reaction(
            conn,
            user_id=EXISTING_USER_ID,
            meme_id=10001,
            reaction_id=1,
            recommended_by="share_link",
        )

    update = _make_update("m_12345_10001", EXISTING_USER_ID)
    context = _make_context("m_12345_10001")

    patches = [
        patch(f"{HANDLER_MODULE}.handle_show_kitchen", new_callable=AsyncMock),
        patch(f"{HANDLER_MODULE}.handle_language_settings", new_callable=AsyncMock),
        patch(f"{HANDLER_MODULE}.handle_invited_user", new_callable=AsyncMock),
        patch(f"{HANDLER_MODULE}.handle_shared_meme_reward", new_callable=AsyncMock),
        patch(f"{HANDLER_MODULE}.send_meme_to_user", new_callable=AsyncMock),
        patch(f"{HANDLER_MODULE}.next_message", new_callable=AsyncMock),
        patch(f"{HANDLER_MODULE}.log_start_event", new_callable=AsyncMock),
        patch("src.tgbot.handlers.stats.wrapped.handle_wrapped", new_callable=AsyncMock),
        patch(
            "src.tgbot.handlers.treasury.giveaway.handle_giveaway",
            new_callable=AsyncMock,
        ),
    ]
    started = [p.start() for p in patches]
    try:
        await handle_start(update, context)
    finally:
        for p in patches:
            p.stop()

    mocks = dict(
        zip(
            [
                "kitchen",
                "lang_settings",
                "invited",
                "shared_reward",
                "send_meme",
                "next_message",
                "log_start",
                "wrapped",
                "giveaway",
            ],
            started,
        )
    )
    mocks["send_meme"].assert_called_once()
    sent_meme = mocks["send_meme"].call_args.args[2]
    assert sent_meme.id == 10001
    mocks["next_message"].assert_not_called()
    mocks["shared_reward"].assert_called_once_with(
        context.bot,
        EXISTING_USER_ID,
        "m_12345_10001",
    )


@pytest.mark.asyncio
async def test_existing_user_legacy_share_link_serves_shared_meme(cleanup):
    from src.tgbot.handlers.start import handle_start

    await _run_handle_start(deep_link=None, user_id=EXISTING_USER_ID)
    async with engine.begin() as conn:
        await create_meme_source(conn, id=10001, language_code="en")
        await create_meme(
            conn,
            id=10001,
            meme_source_id=10001,
            language_code="en",
            telegram_file_id="test_shared_file_id",
        )

    update = _make_update("s_12345_10001", EXISTING_USER_ID)
    context = _make_context("s_12345_10001")

    patches = [
        patch(f"{HANDLER_MODULE}.handle_show_kitchen", new_callable=AsyncMock),
        patch(f"{HANDLER_MODULE}.handle_language_settings", new_callable=AsyncMock),
        patch(f"{HANDLER_MODULE}.handle_invited_user", new_callable=AsyncMock),
        patch(f"{HANDLER_MODULE}.handle_shared_meme_reward", new_callable=AsyncMock),
        patch(f"{HANDLER_MODULE}.send_meme_to_user", new_callable=AsyncMock),
        patch(f"{HANDLER_MODULE}.next_message", new_callable=AsyncMock),
        patch(f"{HANDLER_MODULE}.log_start_event", new_callable=AsyncMock),
        patch("src.tgbot.handlers.stats.wrapped.handle_wrapped", new_callable=AsyncMock),
        patch(
            "src.tgbot.handlers.treasury.giveaway.handle_giveaway",
            new_callable=AsyncMock,
        ),
    ]
    started = [p.start() for p in patches]
    try:
        await handle_start(update, context)
    finally:
        for p in patches:
            p.stop()

    mocks = dict(
        zip(
            [
                "kitchen",
                "lang_settings",
                "invited",
                "shared_reward",
                "send_meme",
                "next_message",
                "log_start",
                "wrapped",
                "giveaway",
            ],
            started,
        )
    )
    mocks["send_meme"].assert_called_once()
    assert mocks["send_meme"].call_args.args[2].id == 10001
    mocks["next_message"].assert_not_called()


@pytest.mark.asyncio
async def test_lazy_init_is_idempotent(cleanup):
    """Re-running /start should not duplicate or re-insert language rows."""
    await _run_handle_start(deep_link=None)

    async with engine.connect() as conn:
        first_rows = (
            await conn.execute(select(user_language).where(user_language.c.user_id == NEW_USER_ID))
        ).fetchall()

    await _run_handle_start(deep_link=None)

    async with engine.connect() as conn:
        second_rows = (
            await conn.execute(select(user_language).where(user_language.c.user_id == NEW_USER_ID))
        ).fetchall()

    assert len(first_rows) == len(second_rows)
    assert len(first_rows) >= 1
