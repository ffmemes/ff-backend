from pydantic import Field
from datetime import datetime

from src.models import CustomModel
from src.storage.constants import MemeType


# minimal data to send a meme
class MemeData(CustomModel):
    meme_id: int
    meme_type: MemeType
    file_id: str
    caption: str | None


class OcrResult(CustomModel):
    model: str
    result: dict
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

    image: list[dict] | None = None
    video: list[dict] | None = None

