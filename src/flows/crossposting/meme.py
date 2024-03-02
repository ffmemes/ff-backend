from html import escape

from prefect import flow, get_run_logger

from src.crossposting.constants import Channel
from src.crossposting.service import (
    get_next_meme_for_tgchannelen,
    get_next_meme_for_tgchannelru,
    log_meme_sent,
)
from src.storage.schemas import MemeData
from src.tgbot.constants import (
    TELEGRAM_CHANNEL_EN_CHAT_ID,
    TELEGRAM_CHANNEL_RU_CHAT_ID,
)
from src.tgbot.senders.meme import send_new_message_with_meme
from src.tgbot.senders.utils import get_random_emoji


def _get_caption_for_crossposting_meme(meme: MemeData, channel: Channel) -> str:
    caption = escape(meme.caption, quote=False) if meme.caption else ""

    ref_link = "https://t.me/ffmemesbot?start=sc_{}_{}".format(meme.id, channel.value)
    emoji = get_random_emoji()
    referral_html = f"""{emoji} <i><a href="{ref_link}">Fast Food Memes</a></i>"""

    return caption + "\n\n" + referral_html


@flow
async def post_meme_to_tgchannelen():
    logger = get_run_logger()

    meme_data = await get_next_meme_for_tgchannelen()
    next_meme = MemeData(**meme_data)
    logger.info(f"Next meme for TG Channel EN: {next_meme.id}")

    next_meme.caption = _get_caption_for_crossposting_meme(
        next_meme, Channel.TG_CHANNEL_EN
    )
    await send_new_message_with_meme(
        TELEGRAM_CHANNEL_EN_CHAT_ID, next_meme, reply_markup=None
    )

    await log_meme_sent(next_meme.id, Channel.TG_CHANNEL_EN)


@flow
async def post_meme_to_tgchannelru():
    logger = get_run_logger()

    meme_data = await get_next_meme_for_tgchannelru()
    next_meme = MemeData(**meme_data)
    logger.info(f"Next meme for TG Channel RU: {next_meme.id}")

    next_meme.caption = _get_caption_for_crossposting_meme(
        next_meme, Channel.TG_CHANNEL_RU
    )

    await send_new_message_with_meme(
        TELEGRAM_CHANNEL_RU_CHAT_ID, next_meme, reply_markup=None
    )

    await log_meme_sent(next_meme.id, Channel.TG_CHANNEL_RU)
