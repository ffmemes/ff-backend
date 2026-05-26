from unittest.mock import AsyncMock, patch

import pytest

from src.tgbot.senders import meme_like_count_experiment as experiment
from src.tgbot.senders.keyboards import meme_reaction_keyboard
from src.tgbot.sharing import MEME_SHARE_BUTTON_URL


def _button_texts(markup) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row]


def test_keyboard_keeps_like_button_plain_without_visible_count(monkeypatch):
    monkeypatch.setattr("src.tgbot.senders.keyboards.random.choice", lambda hearts: "❤️")

    markup = meme_reaction_keyboard(
        meme_id=1,
        user_id=2,
        referral_button_text="Memes",
        visible_like_count=None,
    )

    assert _button_texts(markup) == ["❤️", "⏬"]


def test_keyboard_renders_share_button_above_reactions(monkeypatch):
    monkeypatch.setattr("src.tgbot.senders.keyboards.random.choice", lambda hearts: "❤️")

    markup = meme_reaction_keyboard(
        meme_id=1,
        user_id=2,
        referral_button_text="Send to a friend",
        visible_like_count=None,
        share_button_variant=MEME_SHARE_BUTTON_URL,
        interface_lang="en",
    )

    assert _button_texts(markup) == ["Send to a friend", "❤️", "⏬"]
    assert markup.inline_keyboard[0][0].url.startswith("https://t.me/share/url?")


def test_keyboard_assigns_random_styles_to_buttons_under_meme(monkeypatch):
    styles = iter(["primary", "success", "danger"])

    monkeypatch.setattr("src.tgbot.senders.keyboards.random.choice", lambda hearts: "❤️")
    monkeypatch.setattr(
        "src.tgbot.buttons.random.choices",
        lambda population, k: [next(styles)],
    )

    markup = meme_reaction_keyboard(
        meme_id=1,
        user_id=2,
        referral_button_text="Send to a friend",
        visible_like_count=None,
        share_button_variant=MEME_SHARE_BUTTON_URL,
        interface_lang="en",
    )

    assert [
        button.to_dict()["style"]
        for row in markup.inline_keyboard
        for button in row
    ] == ["primary", "success", "danger"]


def test_keyboard_renders_visible_like_count(monkeypatch):
    monkeypatch.setattr("src.tgbot.senders.keyboards.random.choice", lambda hearts: "❤️")

    markup = meme_reaction_keyboard(
        meme_id=1,
        user_id=2,
        referral_button_text="Memes",
        visible_like_count=12,
    )

    assert _button_texts(markup) == ["❤️ 12", "⏬"]


def test_keyboard_can_mark_reaction_context(monkeypatch):
    monkeypatch.setattr("src.tgbot.senders.keyboards.random.choice", lambda hearts: "❤️")

    markup = meme_reaction_keyboard(
        meme_id=1,
        user_id=2,
        referral_button_text="Memes",
        reaction_context="onboard",
    )

    assert markup.inline_keyboard[0][0].callback_data == "r:1:1:onboard"
    assert markup.inline_keyboard[0][1].callback_data == "r:1:2:onboard"


def test_like_count_assignment_is_stable():
    first = experiment.build_meme_like_count_assignment(123)
    second = experiment.build_meme_like_count_assignment(123)

    assert first == second
    assert first[0] in {
        experiment.MEME_LIKE_COUNT_CONTROL,
        experiment.MEME_LIKE_COUNT_TREATMENT,
    }
    assert first[1]["min_visible_likes"] == experiment.MEME_LIKE_COUNT_MIN_VISIBLE_LIKES
    assert first[1]["shows_dislikes"] is False


@pytest.mark.asyncio
async def test_visible_like_count_is_hidden_for_control():
    with patch(
        "src.tgbot.senders.meme_like_count_experiment.get_or_assign_meme_like_count_variant",
        new_callable=AsyncMock,
        return_value=experiment.MEME_LIKE_COUNT_CONTROL,
    ):
        visible = await experiment.get_visible_meme_like_count(123, 50)

    assert visible is None


@pytest.mark.asyncio
async def test_visible_like_count_uses_threshold_for_treatment():
    with patch(
        "src.tgbot.senders.meme_like_count_experiment.get_or_assign_meme_like_count_variant",
        new_callable=AsyncMock,
        return_value=experiment.MEME_LIKE_COUNT_TREATMENT,
    ):
        below_threshold = await experiment.get_visible_meme_like_count(123, 4)
        at_threshold = await experiment.get_visible_meme_like_count(123, 5)

    assert below_threshold is None
    assert at_threshold == 5


@pytest.mark.asyncio
async def test_assignment_error_falls_back_to_hidden_count():
    with patch(
        "src.tgbot.senders.meme_like_count_experiment.get_or_assign_meme_like_count_variant",
        new_callable=AsyncMock,
        side_effect=RuntimeError("db unavailable"),
    ):
        visible = await experiment.get_visible_meme_like_count(123, 50)

    assert visible is None
