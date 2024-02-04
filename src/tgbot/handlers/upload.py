"""
    Methods for Meme uploading via bot:
    - user forwards a message
    - user sends a new message
"""


from telegram import Update
from telegram.ext import (
    ContextTypes,
)

# TODO: do we need separate handlers?


async def handle_forward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """When a user forwards a tg message to a bot"""
    print(update)

    att = update.message.effective_attachment
    print(att)

    # TODO: save meme to meme_raw_upload
    # trigger ETL ?
    # send to modetation


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """When a user creates & sends a new message with a meme to a bot"""
    print(update)
