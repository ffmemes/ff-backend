from pydantic import ConfigDict
from telegram import InlineKeyboardMarkup

from src.models import CustomModel


class Popup(CustomModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    text: str
    reply_markup: InlineKeyboardMarkup
