from fastapi import (
    APIRouter, 
    BackgroundTasks,
    status,
)

from src.tgbot.bot import process_event
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
    worker: BackgroundTasks,
) -> dict:
    print("PAYLOAD:", payload)
    worker.add_task(process_event, payload)

    # remove buttons with callback 
    if "callback_query" in payload:
        return {
            "method": "editMessageReplyMarkup",
            "chat_id": payload["callback_query"]["message"]["chat"]["id"],
            "message_id": payload["callback_query"]["message"]["message_id"],
            # "reply_markup":  # TODO: remove only callback buttons
        }

    return {
        "ok:": True,
    }
