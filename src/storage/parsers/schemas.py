from datetime import datetime

from src.models import CustomModel


class TgChannelPostParsingResult(CustomModel):
    post_id: int
    url: str
    content: str  # post text
    media: list[dict] | None
    views: int
    date: datetime

    mentions: list[str] | None  # mentioned usernames
    hashtags: list[str] | None
    forwarded: dict | None
    forwarded_url: str | None  # url to forwarded post
    link_preview: dict | None
    out_links: list[str] | None

