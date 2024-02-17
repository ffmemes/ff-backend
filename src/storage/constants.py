from enum import Enum

MEME_RAW_TELEGRAM_MEME_SOURCE_POST_UNIQUE_CONSTRAINT = (
    "meme_raw_telegram_meme_source_id_post_id_key"
)
MEME_RAW_VK_MEME_SOURCE_POST_UNIQUE_CONSTRAINT = (
    "meme_raw_vk_meme_source_id_post_id_key"
)
MEME_MEME_SOURCE_RAW_MEME_UNIQUE_CONSTRAINT = "meme_meme_source_id_raw_meme_id_key"


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
    USER_UPLOAD = "user upload"


class MemeSourceStatus(str, Enum):
    IN_MODERATION = "in_moderation"
    PARSING_ENABLED = "parsing_enabled"
    PARSING_DISABLED = "parsing_disabled"


class MemeStatus(str, Enum):
    CREATED = "created"
    OK = "ok"
    DUPLICATE = "duplicate"
    AD = "ad"
    BROKEN_CONTENT_LINK = "broken_content_link"

    # TODO: more statuses?
    # IN_MODERATION = "in_moderation"
