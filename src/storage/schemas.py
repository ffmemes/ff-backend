from pydantic import Field
from datetime import datetime

from src.models import CustomModel
from src.storage.constants import MemeType


# minimal data to send a meme
class MemeData(CustomModel):
    id: int
    type: MemeType
    telegram_file_id: str
    caption: str | None
    recommended_by: str


class OcrResult(CustomModel):
    text: str
    model: str
    raw_result: dict
    calculated_at: datetime = Field(default_factory=datetime.utcnow)
