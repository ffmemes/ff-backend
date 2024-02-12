from enum import Enum

from src.storage.constants import Language

DEFAULT_USER_LANGUAGE = Language.EN


class UserType(str, Enum):
    WAITLIST = "waitlist"
    USER = "user"
    ACTIVE_USER = "active_user"
    SUPER_USER = "super_user"

    GHOSTED = "ghosted"  # ignoring the bot
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


USER_SAVE_LANGUAGES_CALLBACK_DATA = "u:save_lang"
USER_SAVE_LANGUAGES_REGEXP = r"^u:save_lang$"

USER_SET_LANG_PATTERN = "u:set_lang_{on_or_off}:{lang_code}"
USER_SET_LANG_REGEXP = r"^u:(set_lang_on|set_lang_off):[a-z]{2}$"

MEME_BUTTON_CALLBACK_DATA_PATTERN = "r:{meme_id}:{reaction_id}"
MEME_BUTTON_CALLBACK_DATA_REGEXP = "^r:"

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
