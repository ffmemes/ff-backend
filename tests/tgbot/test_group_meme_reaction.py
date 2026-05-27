from src.tgbot.handlers.chat.group_meme_reaction import build_meme_reaction_keyboard


def test_group_meme_reaction_keyboard_assigns_random_styles(monkeypatch):
    styles = iter(["success", "danger"])

    monkeypatch.setattr(
        "src.tgbot.buttons.random.choices",
        lambda population, k: [next(styles)],
    )

    markup = build_meme_reaction_keyboard(meme_id=42, likes=3, dislikes=2)

    assert [button.to_dict()["style"] for button in markup.inline_keyboard[0]] == [
        "success",
        "danger",
    ]
    assert [button.callback_data for button in markup.inline_keyboard[0]] == [
        "cmr:42:1",
        "cmr:42:2",
    ]
