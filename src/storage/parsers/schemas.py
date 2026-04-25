from datetime import datetime

from src.models import CustomModel


class TgChannelPostParsingResult(CustomModel):
    post_id: int
    url: str
    content: str | None = None  # post text
    media: list[dict] | None = None
    views: int
    date: datetime

    mentions: list[str] | None = None  # mentioned usernames
    hashtags: list[str] | None = None
    forwarded: dict | None = None
    forwarded_url: str | None = None  # url to forwarded post
    link_preview: dict | None = None
    out_links: list[str] | None = None


class VkGroupPostParsingResult(CustomModel):
    post_id: str
    url: str
    content: str | None = None  # post text
    media: list[str]
    date: datetime
    views: int
    likes: int
    reposts: int
    comments: int
