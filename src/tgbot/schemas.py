from datetime import datetime

from pydantic import ConfigDict
from telegram import InlineKeyboardMarkup

from src.models import CustomModel


class UserTg(CustomModel):
    id: int
    username: str | None
    first_name: str
    last_name: str | None
    is_premium: bool
    language_code: str
    deep_link: str | None

    created_at: datetime
    updated_at: datetime


class Popup(CustomModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    text: str
    reply_markup: InlineKeyboardMarkup
