from src.tgbot.service import add_user_language
from src.tgbot.constants import DEFAULT_USER_LANGUAGE


async def init_user_languages_from_tg_language_code(
    user_id: int,  
    tg_language_code: str | None
):
    # TODO: refactor this
    # the goal is to ini languages with popular language: ru or en

    if tg_language_code is not None:
        await add_user_language(user_id, tg_language_code)


    if tg_language_code in ["uk", "ru"]:  # slavic languages
        await add_user_language(user_id, "ru")
    else:
        await add_user_language(user_id, "en")

