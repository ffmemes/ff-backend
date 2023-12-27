from datetime import datetime

from src.models import CustomModel


class TgChannelPostParsingResult(CustomModel):
    post_id: int
    views: int
    date: datetime
    # TODO: add other columns
