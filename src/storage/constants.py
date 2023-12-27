from enum import Enum


class MemeType(str, Enum):
    IMAGE = "image"
    ANIMATION = "animation"
    VIDEO = "video"


class MemeSourceType(str, Enum):
    TELEGRAM = "telegram"
    VK = "vk"
    REDDIT = "reddit"

    # TODO: add memes uploaded by users


class MemeSourceStatus(str, Enum):
    IN_MODERATION = "in_moderation"
    PARSING_ENABLED = "parsing_enabled"
    PARSING_DISABLED = "parsing_disabled"