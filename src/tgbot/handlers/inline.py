from telegram import (
    InlineQueryResultCachedPhoto,
    InlineQueryResultsButton,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from src.config import settings
from src.localizer import t
from src.tgbot.constants import (
    INLINE_SEARCH_REQUEST_DEEPLINK,
)
from src.tgbot.exceptions import UserNotFound
from src.tgbot.senders.utils import get_random_emoji
from src.tgbot.service import (
    create_inline_chosen_result_log,
    create_inline_search_log,
    search_memes_for_inline_query,
)
from src.tgbot.user_info import get_user_info

MIN_SEARCH_QUERY_LENGTH = 3
MAX_SEARCH_QUERY_LENGTH = 128
INLINE_SEARCH_RESULT_CACHE_SECONDS = 60 * 60 * 12  # 12 hours


def get_inline_result_ref_link(user_id: int, meme_id: int):
    deep_link = f"ir_{user_id}_{meme_id}"  # inline result
    return f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={deep_link}"


def get_inline_result_caption(meme, user_info):
    # caption = escape_html(meme["caption"]) if meme["caption"] else ""
    caption = ""

    ref_link = get_inline_result_ref_link(user_info["id"], meme["id"])
    emoji = get_random_emoji()
    caption += f"""{emoji} <a href="{ref_link}">Fast Food Memes</a>"""

    return caption


async def search_inline(update: Update, _: ContextTypes.DEFAULT_TYPE):
    try:
        user_info = await get_user_info(update.effective_user.id)
    except UserNotFound:
        # user doesn't exist. Tell them to start up the bot
        button = InlineQueryResultsButton(
            text=t("inline.you_need_to_register", update.effective_user.language_code),
            start_parameter=INLINE_SEARCH_REQUEST_DEEPLINK,
        )
        await update.inline_query.answer([], button=button, cache_time=0)
        return

    query = update.inline_query.query.strip().lower()

    if len(query) == 0:
        # TODO: show trending / recommended memes
        return await update.inline_query.answer(
            [],
            button=InlineQueryResultsButton(
                text=t("inline.enter_your_query", user_info["interface_lang"]),
                start_parameter=INLINE_SEARCH_REQUEST_DEEPLINK,
            ),
        )
    elif len(query) < MIN_SEARCH_QUERY_LENGTH:
        return await update.inline_query.answer(
            [],
            button=InlineQueryResultsButton(
                text=t("inline.search_query_too_short", user_info["interface_lang"]),
                start_parameter=INLINE_SEARCH_REQUEST_DEEPLINK,
            ),
        )
    if len(query) >= MAX_SEARCH_QUERY_LENGTH:
        return await update.inline_query.answer(
            [],
            button=InlineQueryResultsButton(
                text=t("inline.search_query_too_long", user_info["interface_lang"]),
                start_parameter=INLINE_SEARCH_REQUEST_DEEPLINK,
            ),
        )

    memes = await search_memes_for_inline_query(query, limit=10)

    if len(memes) == 0:
        no_results_button = InlineQueryResultsButton(
            text=t("inline.no_results", user_info["interface_lang"]),
            start_parameter=INLINE_SEARCH_REQUEST_DEEPLINK,
        )
        await update.inline_query.answer([], button=no_results_button)
        return

    results = [
        InlineQueryResultCachedPhoto(
            id=str(meme["id"]),
            photo_file_id=meme["telegram_file_id"],
            caption=get_inline_result_caption(meme, user_info),
            parse_mode=ParseMode.HTML,
        )
        for meme in memes
    ]

    await update.inline_query.answer(
        results, cache_time=INLINE_SEARCH_RESULT_CACHE_SECONDS
    )

    await create_inline_search_log(
        user_id=update.effective_user.id,
        query=query,
        chat_type=update.inline_query.chat_type,
    )


async def handle_chosen_inline_result(update: Update, _: ContextTypes.DEFAULT_TYPE):
    chosen_inline_result = update.chosen_inline_result
    await create_inline_chosen_result_log(
        user_id=chosen_inline_result.from_user.id,
        result_id=chosen_inline_result.result_id,
        query=update.chosen_inline_result.query,
    )
