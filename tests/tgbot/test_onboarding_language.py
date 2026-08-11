from telegram import User

from src.tgbot.handlers.language import (
    resolve_onboarding_auto_language,
)


def _user(**kwargs) -> User:
    defaults = dict(
        id=1,
        first_name="Alex",
        last_name="Smith",
        is_bot=False,
        language_code="en",
    )
    defaults.update(kwargs)
    return User(**defaults)


def test_cyrillic_name_auto_ru_even_if_tg_en():
    user = _user(first_name="Бот", last_name="Test", language_code="en")
    assert resolve_onboarding_auto_language(user) == "ru"


def test_tg_ru_auto_ru():
    assert resolve_onboarding_auto_language(_user(language_code="ru")) == "ru"


def test_tg_uk_auto_uk():
    assert resolve_onboarding_auto_language(_user(language_code="uk")) == "uk"


def test_tg_en_asks():
    assert resolve_onboarding_auto_language(_user(language_code="en")) is None


def test_tg_es_auto():
    assert resolve_onboarding_auto_language(_user(language_code="es")) == "es"
