import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

spec = importlib.util.spec_from_file_location("e2e_smoke", SCRIPTS_DIR / "e2e_smoke.py")
assert spec and spec.loader
e2e_smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e2e_smoke)


class UrlButton:
    url = "https://t.me/share/url?url=https%3A%2F%2Ft.me%2Fffmemesbot"


def _message_with_buttons(*buttons):
    return SimpleNamespace(
        reply_markup=SimpleNamespace(
            rows=[SimpleNamespace(buttons=list(buttons))],
        )
    )


def test_has_reaction_buttons_ignores_url_buttons_without_data():
    msg = _message_with_buttons(
        UrlButton(),
        SimpleNamespace(data=b"r:123:1"),
    )

    assert e2e_smoke.has_reaction_buttons(msg) is True


def test_find_like_button_skips_url_buttons_before_reaction_row():
    like_button = SimpleNamespace(data=b"r:123:1")
    msg = _message_with_buttons(
        UrlButton(),
        SimpleNamespace(data=b"r:123:2"),
        like_button,
    )

    assert e2e_smoke.find_like_button(msg) is like_button


def test_has_reaction_buttons_returns_false_for_url_only_keyboard():
    msg = _message_with_buttons(UrlButton())

    assert e2e_smoke.has_reaction_buttons(msg) is False
