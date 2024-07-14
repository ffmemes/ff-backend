import random

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from src.storage.constants import (
    MemeSourceStatus,
)
from src.tgbot.constants import (
    MEME_BUTTON_CALLBACK_DATA_PATTERN,
    MEME_QUEUE_IS_EMPTY_ALERT_CALLBACK_DATA,
    MEME_SOURCE_SET_LANG_PATTERN,
    Reaction,
)

# IDEA: use sometimes another emoji pair like 🤣/🤮

HEART_EMOJI = ["❤️", "♥️", "💙", "💜", "💛", "🧡", "💚", "🩵"]


def meme_reaction_keyboard(meme_id: int, user_id: int):
    heart = random.choice(HEART_EMOJI)
    like, dislike = heart, "⏬"
    # like, dislike = "👍", "👎"

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    like,
                    callback_data=MEME_BUTTON_CALLBACK_DATA_PATTERN.format(
                        meme_id=meme_id, reaction_id=Reaction.LIKE
                    ),
                ),
                InlineKeyboardButton(
                    dislike,
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
