from telegram import User

from src.tgbot.service import add_user_languages

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
    """
    When user press /start we add languages to user
    """
    languages_to_add = set()

    name_with_slavic_letters = len(set(tg_user.full_name) & set(RUSSIAN_ALPHABET)) > 0
    if name_with_slavic_letters:
        languages_to_add.add("ru")

    # add languages ru / en since they are the most common
    if tg_user.language_code in ALMOST_CIS_LANGUAGES:
        languages_to_add.add("ru")
    else:
        languages_to_add.add("en")

    if tg_user.language_code is not None:
        languages_to_add.add(tg_user.language_code)

    await add_user_languages(tg_user.id, languages_to_add)


async def handle_lang(update, context):
    pass
