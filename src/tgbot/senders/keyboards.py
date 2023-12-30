from telegram import (
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
)

from src.tgbot.constants import (
    Reaction, 
    MEME_BUTTON_CALLBACK_DATA_PATTERN,
    MEME_QUEUE_IS_EMPTY_ALERT_CALLBACK_DATA,
)


# IDEA: use sometimes another emoji pair like 🤣/🤮 


def get_meme_keyboard(meme_id):
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


def get_queue_empty_alert_keyboard(emoji: str = "⏳"):
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton(
                emoji,
                callback_data=MEME_QUEUE_IS_EMPTY_ALERT_CALLBACK_DATA,
            )
        ]]
    )
