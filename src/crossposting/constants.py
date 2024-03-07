from enum import Enum


class Channel(str, Enum):
    TG_CHANNEL_EN = "tgchannelen"
    TG_CHANNEL_RU = "tgchannelru"
    VK_GROUP_RU = "vkru"
