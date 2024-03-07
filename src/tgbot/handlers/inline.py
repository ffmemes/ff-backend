from html import escape as escape_html
from uuid import uuid4

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultCachedPhoto,
    InlineQueryResultsButton,
    Update,
)
from telegram.ext import ContextTypes

from src.localizer import t
from src.tgbot.constants import (
    DAY_IN_SECONDS,
    INLINE_SEARCH_RESULT_DEEPLINK,
    INLINE_SEARCH_START_DEEPLINK,
)
from src.tgbot.exceptions import NoUserInfoFound
from src.tgbot.handlers.language import (
    get_active_language_from_user_languages,
    get_user_languages_from_language_code_and_full_name,
)
from src.tgbot.service import search_memes_for_inline_query
from src.tgbot.user_info import get_user_info

MIN_SEARCH_QUERY_LENGTH = 3
MAX_SEARCH_QUERY_LENGTH = 128
INLINE_SEARCH_RESULT_CACHE_IN_SECONDS = 60 * 60 * 12  # 12 hours


async def search_inline(update: Update, _: ContextTypes.DEFAULT_TYPE):
    try:
        user_info = await get_user_info(update.effective_user.id)
    except NoUserInfoFound:
        print(f"User {update.effective_user.id} is not registered. told him to")
        # user doesn't exist. Tell them to start up the bot
        user_languages = get_user_languages_from_language_code_and_full_name(
            update.effective_user.language_code, update.effective_user.full_name
        )
        language_to_use = get_active_language_from_user_languages(user_languages)
        button = InlineQueryResultsButton(
            text=t("inline.you_need_to_register", language_to_use),
            start_parameter=INLINE_SEARCH_START_DEEPLINK,
        )
        await update.inline_query.answer([], button=button, cache_time=0)
        return

    query = update.inline_query.query.strip().lower()

    if len(query) == 0:
        print("search query not provided")
        await update.inline_query.answer(
            [],
            button=InlineQueryResultsButton(
                text=t("inline.enter_your_query", user_info["interface_lang"]),
                start_parameter=INLINE_SEARCH_START_DEEPLINK,
            ),
            cache_time=DAY_IN_SECONDS,
        )
        return
    elif len(query) < MIN_SEARCH_QUERY_LENGTH:
        print("search query too short")
        return await update.inline_query.answer(
            [],
            button=InlineQueryResultsButton(
                text=t("inline.search_query_too_short", user_info["interface_lang"]),
                start_parameter=INLINE_SEARCH_START_DEEPLINK,
            ),
        )
    if len(query) >= MAX_SEARCH_QUERY_LENGTH:
        print("search query too long")
        return await update.inline_query.answer(
            [],
            button=InlineQueryResultsButton(
                text=t("inline.search_query_too_long", user_info["interface_lang"]),
                start_parameter=INLINE_SEARCH_START_DEEPLINK,
            ),
        )

    memes = await search_memes_for_inline_query(query, update.effective_user.id, 10)

    # save search query
    print(f"#{update.effective_user.id} searched for {query}")
    # save search query
    if len(memes) == 0:
        print(f"#{update.effective_user.id} searched for {query} and did not find shit")
        no_results_button = InlineQueryResultsButton(
            text=t("inline.no_results", user_info["interface_lang"]),
            start_parameter=INLINE_SEARCH_START_DEEPLINK,
        )
        await update.inline_query.answer([], button=no_results_button)
        return

    results = [
        InlineQueryResultCachedPhoto(
            id=uuid4(),
            photo_file_id=meme["telegram_file_id"],
            caption=escape_html(meme["caption"]) if meme["caption"] else "",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "text",
                            url=f"https://t.me/ffmemesbot?start={INLINE_SEARCH_RESULT_DEEPLINK}",
                        ),
                    ]
                ]
            ),
        )
        for meme in memes
    ]

    await update.inline_query.answer(
        results, cache_time=INLINE_SEARCH_RESULT_CACHE_IN_SECONDS
    )
