from telegram import (
    InlineQueryResultCachedGif,
    InlineQueryResultCachedPhoto,
    InlineQueryResultCachedVideo,
    InlineQueryResultsButton,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from src.localizer import t
from src.storage.constants import MemeType
from src.tgbot.constants import (
    INLINE_SEARCH_REQUEST_DEEPLINK,
)
from src.tgbot.exceptions import UserNotFound
from src.tgbot.senders.utils import get_random_emoji
from src.tgbot.service import (
    create_inline_chosen_result_log,
    create_inline_search_log,
    get_shareable_meme_by_id,
    search_memes_for_inline_query,
)
from src.tgbot.sharing import get_meme_share_link
from src.tgbot.user_info import get_user_info

MIN_SEARCH_QUERY_LENGTH = 3
MAX_SEARCH_QUERY_LENGTH = 128
INLINE_SEARCH_RESULT_LIMIT = 20
INLINE_SEARCH_RESULT_CACHE_SECONDS = 60 * 60 * 12  # 12 hours


def get_inline_result_ref_link(user_id: int, meme_id: int):
    return get_meme_share_link(user_id, meme_id)


def get_inline_result_caption(meme, user_info):
    # caption = escape_html(meme["caption"]) if meme["caption"] else ""
    caption = ""

    ref_link = get_inline_result_ref_link(user_info["id"], meme["id"])
    emoji = get_random_emoji()
    caption += f"""{emoji} <a href="{ref_link}">Fast Food Memes</a>"""

    return caption


def parse_exact_meme_inline_query(query: str) -> int | None:
    if not query.startswith("#"):
        return None

    meme_id = query[1:]
    if not meme_id.isdigit():
        return None

    return int(meme_id)


def build_inline_meme_result(meme: dict, user_info: dict):
    caption = get_inline_result_caption(meme, user_info)
    meme_type = MemeType(meme["type"])
    if meme_type == MemeType.IMAGE:
        return InlineQueryResultCachedPhoto(
            id=str(meme["id"]),
            photo_file_id=meme["telegram_file_id"],
            caption=caption,
            parse_mode=ParseMode.HTML,
        )
    if meme_type == MemeType.VIDEO:
        return InlineQueryResultCachedVideo(
            id=str(meme["id"]),
            video_file_id=meme["telegram_file_id"],
            title="Fast Food Memes",
            caption=caption,
            parse_mode=ParseMode.HTML,
        )
    if meme_type == MemeType.ANIMATION:
        return InlineQueryResultCachedGif(
            id=str(meme["id"]),
            gif_file_id=meme["telegram_file_id"],
            caption=caption,
            parse_mode=ParseMode.HTML,
        )
    return None


async def answer_exact_meme_inline_query(update: Update, user_info: dict, meme_id: int) -> None:
    meme = await get_shareable_meme_by_id(meme_id)
    result = build_inline_meme_result(meme, user_info) if meme else None
    results = [result] if result else []
    await update.inline_query.answer(
        results,
        cache_time=INLINE_SEARCH_RESULT_CACHE_SECONDS,
        is_personal=True,
    )

    await create_inline_search_log(
        user_id=update.effective_user.id,
        query=update.inline_query.query.strip().lower(),
        chat_type=update.inline_query.chat_type,
    )


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

    exact_meme_id = parse_exact_meme_inline_query(query)
    if exact_meme_id is not None:
        return await answer_exact_meme_inline_query(update, user_info, exact_meme_id)

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
    elif len(query) > MAX_SEARCH_QUERY_LENGTH:  # Bug fix: Changed '>=' to '>'
        return await update.inline_query.answer(
            [],
            button=InlineQueryResultsButton(
                text=t("inline.search_query_too_long", user_info["interface_lang"]),
                start_parameter=INLINE_SEARCH_REQUEST_DEEPLINK,
            ),
        )

    memes = await search_memes_for_inline_query(query, limit=INLINE_SEARCH_RESULT_LIMIT)

    if len(memes) == 0:
        no_results_button = InlineQueryResultsButton(
            text=t("inline.no_results", user_info["interface_lang"]),
            start_parameter=INLINE_SEARCH_REQUEST_DEEPLINK,
        )
        await update.inline_query.answer([], button=no_results_button)
        return

    results = [result for meme in memes if (result := build_inline_meme_result(meme, user_info))]

    await update.inline_query.answer(
        results,
        cache_time=INLINE_SEARCH_RESULT_CACHE_SECONDS,
        is_personal=True,
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
        query=chosen_inline_result.query,
    )
