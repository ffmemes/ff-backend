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
    TELEGRAM_CHANNEL_FFMEMES_CHAT_ID,
    TELEGRAM_CHANNEL_RU_CHAT_ID,
)

CHANNEL_CHAT_IDS: dict[str, int] = {
    "ru": TELEGRAM_CHANNEL_RU_CHAT_ID,
    "en": TELEGRAM_CHANNEL_EN_CHAT_ID,
    "ffmemes": TELEGRAM_CHANNEL_FFMEMES_CHAT_ID,
}


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
    photo_bytes: bytes | None = None,
    button_text: str | None = None,
    button_url: str | None = None,
):
    """Post an editorial message to one of the FFMemes Telegram channels.

    Args:
        text: HTML-formatted message text.
        channel: "ru" (@fastfoodmemes — main RU meme channel),
            "en" (@fast_food_memes — EN meme channel), or
            "ffmemes" (@ffmemes — RU build-in-public / product / process).
        photo_url: URL to a photo to attach.
        photo_file_id: Telegram file_id of a photo to attach.
        photo_bytes: Raw image bytes for generated/local visuals.
        button_text: Optional inline button label.
        button_url: Optional inline button URL.
    """
    logger = get_run_logger()

    try:
        chat_id = CHANNEL_CHAT_IDS[channel]
    except KeyError as exc:
        raise ValueError(
            f"Unknown channel {channel!r}; expected one of {sorted(CHANNEL_CHAT_IDS)}"
        ) from exc

    reply_markup = None
    if button_text and button_url:
        reply_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton(text=button_text, url=button_url)]]
        )

    media_sources = [photo_file_id is not None, photo_url is not None, photo_bytes is not None]
    if sum(media_sources) > 1:
        raise ValueError("Pass exactly one of photo_file_id, photo_url, or photo_bytes")

    if photo_file_id is not None:
        photo = photo_file_id
    elif photo_url is not None:
        photo = photo_url
    else:
        photo = photo_bytes

    if photo is not None:
        send_kwargs = {}
        if photo_bytes is not None and photo is photo_bytes:
            send_kwargs["filename"] = "editorial.png"
        msg = await bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            **send_kwargs,
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
