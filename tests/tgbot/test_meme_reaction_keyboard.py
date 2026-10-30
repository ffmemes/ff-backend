from src.tgbot.senders.keyboards import meme_reaction_keyboard


def _button_texts(markup) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row]


def test_keyboard_keeps_like_button_plain(monkeypatch):
    monkeypatch.setattr("src.tgbot.senders.keyboards.random.choice", lambda hearts: "❤️")

    markup = meme_reaction_keyboard(
        meme_id=1,
        user_id=2,
        referral_button_text="Memes",
    )

    assert _button_texts(markup) == ["❤️", "⏬"]


def test_keyboard_renders_share_button_above_reactions(monkeypatch):
    monkeypatch.setattr("src.tgbot.senders.keyboards.random.choice", lambda hearts: "❤️")

    markup = meme_reaction_keyboard(
        meme_id=1,
        user_id=2,
        referral_button_text="Send to a friend",
        share_button=True,
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
        share_button=True,
        interface_lang="en",
    )

    assert [button.to_dict()["style"] for row in markup.inline_keyboard for button in row] == [
        "primary",
        "success",
        "danger",
    ]


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
