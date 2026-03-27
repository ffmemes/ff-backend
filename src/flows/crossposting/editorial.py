"""
Editorial posting flow for @ffmemes channel.

Posts text/media editorial content (announcements, data insights, etc.)
to the Telegram channel. Triggered on-demand, not on a cron schedule.

Usage (via Prefect CLI or API):
    prefect deployment run "Post Editorial to Channel/Post Editorial"
"""

from prefect import flow, get_run_logger
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from src.flows.hooks import notify_telegram_on_failure
from src.tgbot.bot import bot
from src.tgbot.constants import (
    TELEGRAM_CHANNEL_EN_CHAT_ID,
    TELEGRAM_CHANNEL_RU_CHAT_ID,
)


@flow(
    retries=1,
    retry_delay_seconds=30,
    timeout_seconds=120,
    on_failure=[notify_telegram_on_failure],
)
async def post_editorial_to_channel(
    text: str,
    channel: str = "ru",
    photo_url: str | None = None,
    photo_file_id: str | None = None,
    button_text: str | None = None,
    button_url: str | None = None,
):
    """Post an editorial message to the @ffmemes channel.

    Args:
        text: HTML-formatted message text.
        channel: "ru" or "en".
        photo_url: URL to a photo to attach.
        photo_file_id: Telegram file_id of a photo to attach.
        button_text: Optional inline button label.
        button_url: Optional inline button URL.
    """
    logger = get_run_logger()

    chat_id = (
        TELEGRAM_CHANNEL_RU_CHAT_ID
        if channel == "ru"
        else TELEGRAM_CHANNEL_EN_CHAT_ID
    )

    reply_markup = None
    if button_text and button_url:
        reply_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton(text=button_text, url=button_url)]]
        )

    photo = photo_file_id or photo_url

    if photo:
        msg = await bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
        logger.info(f"Posted editorial photo to {channel} channel: msg_id={msg.message_id}")
    else:
        msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=reply_markup,
        )
        logger.info(f"Posted editorial text to {channel} channel: msg_id={msg.message_id}")

    return msg.message_id
