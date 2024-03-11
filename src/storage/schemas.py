from datetime import datetime

from pydantic import Field

from src.models import CustomModel
from src.storage.constants import MemeType


class MemeData(CustomModel):
    id: int
    type: MemeType
    telegram_file_id: str
    caption: str | None
    recommended_by: str | None = None


class OcrResult(CustomModel):
    text: str
    model: str
    raw_result: dict
    calculated_at: datetime = Field(default_factory=datetime.utcnow)


class MemeUserUpload(CustomModel):
    message_id: int
    chat: dict

    content: str | None = None
    date: datetime

    out_links: list[str] | None = None
    mentions: list[str] | None = None # mentioned usernames
    hashtags: list[str] | None = None
    forwarded: dict | None = None
    media: list[dict] | None = None

