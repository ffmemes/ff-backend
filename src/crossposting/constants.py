from enum import Enum


class Channel(str, Enum):
    TG_CHANNEL_EN = "tg_channel_en"
    TG_CHANNEL_RU = "tg_channel_ru"
    VK_GROUP_RU = "vk_group_ru"
