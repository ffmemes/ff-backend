from typing import Any

from pydantic import model_validator

from src.models import CustomModel
from src.storage.constants import MemeType


class MemeData(CustomModel):
    id: int
    type: MemeType
    telegram_file_id: str
    caption: str | None
    language_code: str | None = None
    recommended_by: str | None = None
    nlikes: int = 0

    @model_validator(mode="before")
    @classmethod
    def validate_caption(cls, values: dict[str, Any]) -> dict[str, Any]:
        caption = values.get("caption")
        if caption is not None:
            values["caption"] = caption[:1000]
        values["nlikes"] = int(values.get("nlikes") or 0)
        return values
