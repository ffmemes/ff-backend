from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    status,
)

from src.tgbot.app import process_event
from src.tgbot.dependencies import validate_webhook_secret
from src.tgbot.utils import remove_buttons_with_callback

router = APIRouter()


@router.post(
    "/webhook",
    dependencies=[Depends(validate_webhook_secret)],
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def tgbot_webhook_events(
    payload: dict,
    worker: BackgroundTasks,
) -> dict:
    worker.add_task(process_event, payload)

    # remove buttons with callback
    if "callback_query" in payload:
        cbqm = payload["callback_query"]["message"]
        if cbqm.get("reply_markup"):  # has buttons
            return {
                "method": "editMessageReplyMarkup",
                "chat_id": cbqm["chat"]["id"],
                "message_id": cbqm["message_id"],
                "reply_markup": remove_buttons_with_callback(cbqm["reply_markup"]),
            }

    return {
        "ok:": True,
    }
