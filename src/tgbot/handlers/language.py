from telegram import User

from src.tgbot.service import add_user_language

RUSSIAN_ALPHABET = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
ALMOST_CIS_LANGUAGES = [
    "uk",
    "ru",
    "bg",
    "be",
    "sr",
    "hr",
    "bs",
    "mk",
    "sl",
    "kz",
    "ky",
    "tg",
    "tt",
    "uz",
    "mn",
    "az",
]


async def init_user_languages_from_tg_user(tg_user: User):
    tg_language_code = tg_user.language_code
    languages_to_add = set()

    name_with_slavic_letters = len(set(tg_user.full_name) & set(RUSSIAN_ALPHABET)) > 0
    if name_with_slavic_letters:
        languages_to_add.add("ru")

    if tg_language_code in ALMOST_CIS_LANGUAGES:
        languages_to_add.add("ru")
    else:
        languages_to_add.add("en")

    if tg_language_code is not None:
        languages_to_add.add(tg_language_code)

    for language in languages_to_add:
        await add_user_language(tg_user.id, language)
