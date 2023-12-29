from enum import Enum
from src.storage.constants import Language


DEFAULT_USER_LANGUAGE = Language.EN


class UserType(str, Enum):    
    USER = "user"
    ACTIVE_USER = "active_user"
    SUPER_USER = "super_user"

    GHOSTED = "ghosted"  # ignoring the bot
    BLOCKED_BOT = "blocked_bot"

    MODERATOR = "moderator"
