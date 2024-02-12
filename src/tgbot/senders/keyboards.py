from functools import cache
from typing import Tuple

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from src.storage.constants import (
    SUPPORTED_LANGUAGES,
    Language,
    MemeSourceStatus,
)
from src.tgbot.constants import (
    MEME_BUTTON_CALLBACK_DATA_PATTERN,
    MEME_QUEUE_IS_EMPTY_ALERT_CALLBACK_DATA,
    MEME_SOURCE_SET_LANG_PATTERN,
    USER_SAVE_LANGUAGES_CALLBACK_DATA,
    USER_SET_LANG_PATTERN,
    Reaction,
)

# IDEA: use sometimes another emoji pair like 🤣/🤮
# TODO: maybe cache every single value here?


def meme_reaction_keyboard(meme_id):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "👍",
                    callback_data=MEME_BUTTON_CALLBACK_DATA_PATTERN.format(
                        meme_id=meme_id, reaction_id=Reaction.LIKE
                    ),
                ),
                InlineKeyboardButton(
                    "👎",
                    callback_data=MEME_BUTTON_CALLBACK_DATA_PATTERN.format(
                        meme_id=meme_id, reaction_id=Reaction.DISLIKE
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
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=lang_code,
                    callback_data=MEME_SOURCE_SET_LANG_PATTERN.format(
                        meme_source_id=meme_source_id, lang_code=lang_code
                    ),
                )
                for lang_code in SUPPORTED_LANGUAGES
            ]
        ]
    )


def meme_source_change_status_keyboard(meme_source_id: int):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"➡️ {status}",
                    callback_data=f"ms:{meme_source_id}:set_status:{status}",
                )
            ]
            for status in MemeSourceStatus
        ]
    )


@cache
def user_language_selection_keyboard(
    enabled_langs: Tuple[Language]
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=lang_code.emoji + ("✅" if lang_code in enabled_langs else ""),
                    callback_data=USER_SET_LANG_PATTERN.format(
                        on_or_off="off" if lang_code in enabled_langs else "on",
                        lang_code=lang_code,
                    ),
                )
                for lang_code in SUPPORTED_LANGUAGES
            ],
            [
                InlineKeyboardButton(
                    "🆗",
                    callback_data=USER_SAVE_LANGUAGES_CALLBACK_DATA,
                )
            ],
        ]
    )
