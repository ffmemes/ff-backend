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
