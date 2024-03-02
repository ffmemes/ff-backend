from enum import Enum


class UserType(str, Enum):
    WAITLIST = "waitlist"
    USER = "user"
    ACTIVE_USER = "active_user"
    SUPER_USER = "super_user"

    # GHOSTED = "ghosted"  # ignoring the bot
    BLOCKED_BOT = "blocked_bot"

    MODERATOR = "moderator"
    ADMIN = "admin"

    @property
    def is_moderator(self) -> bool:
        return self in (self.MODERATOR, self.ADMIN)


class Reaction(int, Enum):
    LIKE = 1
    DISLIKE = 2

    @property
    def is_positive(self) -> bool:
        return self in (self.LIKE,)


MEME_BUTTON_CALLBACK_DATA_PATTERN = "r:{meme_id}:{reaction_id}"
MEME_BUTTON_CALLBACK_DATA_REGEXP = "^r:"

POPUP_BUTTON_CALLBACK_DATA_PATTERN = "p:{popup_id}"
POPUP_BUTTON_CALLBACK_DATA_REGEXP = "^p:"

MEME_QUEUE_IS_EMPTY_ALERT_CALLBACK_DATA = "q:empty"

MEME_SOURCE_SET_LANG_PATTERN = "ms:{meme_source_id}:set_lang:{lang_code}"
MEME_SOURCE_SET_LANG_REGEXP = r"^ms:\d+:set_lang:\w{2}$"

MEME_SOURCE_SET_STATUS_PATTERN = "ms:{meme_source_id}:set_status:{status}"
MEME_SOURCE_SET_STATUS_REGEXP = r"^ms:\d+:set_status:\w+$"

LOADING_EMOJIS = [
    "🕛",
    "🕧",
    "🕐",
    "🕜",
    "🕑",
    "🕝",
    "🕒",
    "🕞",
    "🕓",
    "🕟",
    "🕔",
    "🕠",
    "🕕",
    "🕡",
    "🕖",
    "🕢",
    "🕗",
    "🕣",
    "🕘",
    "🕤",
    "🕙",
    "🕥",
    "🕚",
    "🕦",
]

TELEGRAM_CHANNEL_EN_CHAT_ID = -1002120551028
TELEGRAM_CHANNEL_EN_LINK = "https://t.me/fast_food_memes"

TELEGRAM_CHANNEL_RU_CHAT_ID = -1001152876229
TELEGRAM_CHANNEL_RU_LINK = "https://t.me/fastfoodmemes"
