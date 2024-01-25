from pydantic import Field
from datetime import datetime

from src.models import CustomModel
from src.storage.constants import MemeType


class BasicMemeData(CustomModel):
    id: int
    type: MemeType
    telegram_file_id: str
    caption: str | None


# minimal data to send a meme
class MemeData(BasicMemeData):
    recommended_by: str


class OcrResult(CustomModel):
    text: str
    model: str
    raw_result: dict
    calculated_at: datetime = Field(default_factory=datetime.utcnow)
