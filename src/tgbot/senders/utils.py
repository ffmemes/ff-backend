from random import choice
from typing import Iterable

from telegram import Message, Update
from telegram.constants import ParseMode

from src.config import settings
from src.tgbot.service import get_user_languages


def get_random_emoji() -> str:
    return choice(
        [
            "👉",
            "🤖",
            "🤣",
            "🌺",
            "🛠️",
            "🐝",
            "🐌",
            "🦋",
            "🦧",
            "🦔",
            "🍭",
            "🍿",
            "🎭",
            "🎲",
            "🏴‍☠️",
            "🃏",
            "💠",
            "🩵",
            "🔖",
            "🗞️",
            "🧾",
            "🎐",
            "🪒",
            "🧫",
            "⚗️",
            "🪪",
            "📟",
            "🖲️",
            "🛖",
            "🗺️",
            "🚤",
            "🦼",
            "🪈",
            "🩰",
            "🏊🏻‍♂️",
            "🤺",
            "🪂",
            "🥋",
            "🛼",
            "🥍",
            "🪀",
            "🫗",
            "🦪",
            "🧆",
            "🫒",
            "🪺",
            "🦩",
            "🦒",
            "🫎",
            "🪿",
            "🧤",
            "🧖🏻‍♂️",
            "🧌",
            "🦿",
            "🍄",
        ]
    )


def get_referral_link(user_id: int, meme_id: int) -> str:
    return f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start=s_{user_id}_{meme_id}"


def get_referral_html(user_id: int, meme_id: int) -> str:
    emoji = get_random_emoji()
    ref_link = get_referral_link(user_id, meme_id)
    return f"""{emoji} <i><a href="{ref_link}">Fast Food Memes</a></i>"""


async def collect_user_languages(
    user_id: int,
    *additional_languages: str | None,
) -> set[str]:
    languages = set(await get_user_languages(user_id))
    for language in additional_languages:
        if language:
            languages.add(language)
    return languages


def has_russian_language(languages: Iterable[str]) -> bool:
    return any(language and language.startswith("ru") for language in languages)


async def send_or_edit(
    prev_update: Update,
    text: str,
    reply_markup: dict,
    disable_web_page_preview: bool = True,
) -> Message:
    if prev_update.callback_query is not None:
        return await prev_update.callback_query.message.edit_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=disable_web_page_preview,
        )

    return await prev_update.message.reply_text(
        text=text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=disable_web_page_preview,
    )
