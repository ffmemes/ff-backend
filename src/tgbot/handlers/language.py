from src.tgbot.service import add_user_language
from src.tgbot.constants import DEFAULT_USER_LANGUAGE


async def init_user_languages_from_tg_language_code(
    user_id: int,  
    tg_language_code: str | None
):
    languages_to_add = set()

    almost_CIS_languages = ["uk", "ru", "bg", "be", "sr", "hr", "bs", "mk", "sl", "kz", "ky", "tg", "tt", "uz"]
    if tg_language_code in almost_CIS_languages:
        languages_to_add.add("ru")
    else:
        languages_to_add.add("en")

    if tg_language_code is not None:
        languages_to_add.add(tg_language_code)

    for language in languages_to_add:
        await add_user_language(user_id, language)

