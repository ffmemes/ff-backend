from datetime import datetime
from typing import Any

from pydantic import Field, model_validator

from src.models import CustomModel
from src.storage.constants import MemeType


class MemeData(CustomModel):
    id: int
    type: MemeType
    telegram_file_id: str
    caption: str | None
    recommended_by: str | None = None

    @model_validator(mode="before")
    @classmethod
    def validate_caption(cls, values: dict[str, Any]) -> dict[str, Any]:
        caption = values.get("caption")
        if caption is not None:
            values["caption"] = caption[:1000]
        return values


class OcrResult(CustomModel):
    text: str
    model: str
    raw_result: dict
    calculated_at: datetime = Field(default_factory=datetime.utcnow)
