import random

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.storage.constants import (
    MemeSourceStatus,
)
from src.tgbot.constants import (
    MEME_BUTTON_CALLBACK_DATA_PATTERN,
    MEME_QUEUE_IS_EMPTY_ALERT_CALLBACK_DATA,
    MEME_SOURCE_SET_LANG_PATTERN,
    Reaction,
)
from src.tgbot.senders.utils import get_referral_link

# IDEA: use sometimes another emoji pair like 🤣/🤮

HEART_EMOJI = ["❤️", "♥️", "💙", "💜", "💛", "🧡", "💚", "🩵"]

RUSSIAN_REFERRAL_BUTTON_TEXTS = [
    "Мемы для тебя",
    "Твои мемы",
    "Еще мемы",
    "Бот с мемами",
    "За мемами",
    "Свежие мемы",
    "Мемы тут",
    "Мемная лента",
    "Мемы рядом",
    "Лови мемы",
]

ENGLISH_REFERRAL_BUTTON_TEXTS = [
    "Memes for you",
    "Your memes",
    "More memes",
    "Meme bot",
    "Grab memes",
    "Fresh memes",
    "Meme feed",
    "Daily memes",
    "Tap memes",
    "Memes inside",
]


def select_referral_button_text(has_russian_language: bool) -> str:
    texts = (
        RUSSIAN_REFERRAL_BUTTON_TEXTS
        if has_russian_language
        else ENGLISH_REFERRAL_BUTTON_TEXTS
    )
    return random.choice(texts)


def meme_reaction_keyboard(
    meme_id: int,
    user_id: int,
    referral_button_text: str,
):
    heart = random.choice(HEART_EMOJI)
    like, dislike = heart, "⏬"
    # like, dislike = "👍", "👎"

    referral_link = get_referral_link(user_id, meme_id)
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    referral_button_text,
                    url=referral_link,
                ),
            ],
            [
                InlineKeyboardButton(
                    like,
                    callback_data=MEME_BUTTON_CALLBACK_DATA_PATTERN.format(
                        meme_id=meme_id, reaction_id=Reaction.LIKE.value
                    ),
                ),
                InlineKeyboardButton(
                    dislike,
                    callback_data=MEME_BUTTON_CALLBACK_DATA_PATTERN.format(
                        meme_id=meme_id, reaction_id=Reaction.DISLIKE.value
                    ),
                ),
            ],
        ]
    )


def queue_empty_alert_keyboard(emoji: str = "⏳"):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    emoji,
                    callback_data=MEME_QUEUE_IS_EMPTY_ALERT_CALLBACK_DATA,
                )
            ]
        ]
    )


def meme_source_language_selection_keyboard(meme_source_id: int):
    # TODO: get languages from some shared consts
    languages = ["ru", "uk", "en", "es", "fr", "de", "fa"]
    per_row = 4
    rows = [languages[i : i + per_row] for i in range(0, len(languages), per_row)]
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"{lang_code}",
                    callback_data=MEME_SOURCE_SET_LANG_PATTERN.format(
                        meme_source_id=meme_source_id, lang_code=lang_code
                    ),
                )
                for lang_code in row
            ]
            for row in rows
        ]
    )


def meme_source_change_status_keyboard(
    meme_source_id: int,
    current_status: MemeSourceStatus | None = None,
):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"➡️ {status}",
                    callback_data=f"ms:{meme_source_id}:set_status:{status}",
                )
            ]
            for status in MemeSourceStatus
            if status != current_status
        ]
    )
