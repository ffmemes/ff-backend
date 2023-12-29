from fastapi import (
    APIRouter, 
    status,
)

from src.tgbot.bot import process_event
from src.tgbot.service import get_all_messages
from src.tgbot.schemas import TgbotMessage

from src.tgbot.dependencies import validate_webhook_secret

router = APIRouter()


@router.post(
    "/webhook",
    dependencies=[validate_webhook_secret],
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def tgbot_webhook_events(
    payload: dict,
) -> dict:
    print("PAYLOAD:", payload)
    await process_event(payload)

    # TODO: explore what we can do here
    # e.g. remove buttons with callback 
    return {
        "ok:": True,
    }
