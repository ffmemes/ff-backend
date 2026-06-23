from scripts.e2e_smoke import button_data, find_like_button, has_reaction_buttons


class _UrlButton:
    url = "https://t.me/share/url?url=https%3A%2F%2Ft.me%2Fffmemesbot"


class _CallbackButton:
    def __init__(self, data: bytes) -> None:
        self.data = data


class _Row:
    def __init__(self, buttons: list[object]) -> None:
        self.buttons = buttons


class _ReplyMarkup:
    def __init__(self, rows: list[_Row]) -> None:
        self.rows = rows


class _Message:
    def __init__(self, buttons: list[object]) -> None:
        self.reply_markup = _ReplyMarkup([_Row(buttons)])


def test_button_data_ignores_url_buttons_without_data() -> None:
    assert button_data(_UrlButton()) == b""


def test_reaction_button_detection_skips_url_buttons() -> None:
    msg = _Message([_UrlButton(), _CallbackButton(b"r:123:1")])

    assert has_reaction_buttons(msg) is True


def test_find_like_button_skips_url_buttons_before_reaction_row() -> None:
    like_button = _CallbackButton(b"r:123:1")
    msg = _Message([_UrlButton(), _CallbackButton(b"r:123:2"), like_button])

    assert find_like_button(msg) is like_button


def test_reaction_button_detection_handles_url_only_markup() -> None:
    msg = _Message([_UrlButton()])

    assert has_reaction_buttons(msg) is False
    assert find_like_button(msg) is None
