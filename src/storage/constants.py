from enum import Enum

MEME_SOURCE_POST_UNIQUE_CONSTRAINT = "meme_source_id_post_id_key"


class MemeType(str, Enum):
    IMAGE = "image"
    ANIMATION = "animation"
    VIDEO = "video"


class MemeSourceType(str, Enum):
    TELEGRAM = "telegram"
    VK = "vk"
    REDDIT = "reddit"
    INSTAGRAM = "instagram"
    TWITTER = "twitter"
    TIKTOK = "tiktok"
    USER_SUBMITTED = "user_submitted"


class MemeSourceStatus(str, Enum):
    IN_MODERATION = "in_moderation"
    PARSING_ENABLED = "parsing_enabled"
    PARSING_DISABLED = "parsing_disabled"