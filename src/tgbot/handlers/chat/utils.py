import asyncio

from telegram import InlineKeyboardMarkup, Message
from telegram.error import BadRequest

MESSAGE_TO_REPLY_NOT_FOUND = "Message to be replied not found"


def _is_missing_reply_error(error: BadRequest) -> bool:
    return MESSAGE_TO_REPLY_NOT_FOUND.lower() in error.message.lower()


async def _reply_and_delete(
    message: Message,
    text: str,
    sleep_sec: int = 5,
    delete_original: bool = True,
    reply_markup: InlineKeyboardMarkup | None = None,
):
    try:
        msg = await message.reply_text(
            text,
            reply_markup=reply_markup,
        )
    except BadRequest as e:
        if not _is_missing_reply_error(e):
            raise
        msg = await message.reply_text(
            text,
            reply_markup=reply_markup,
            do_quote=False,
        )
    await asyncio.sleep(sleep_sec)
    await msg.delete()

    if delete_original:
        try:
            await message.delete()
        except BadRequest:
            pass
        return
