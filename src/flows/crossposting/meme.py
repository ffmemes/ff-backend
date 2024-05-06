from html import escape

from prefect import flow, get_run_logger

from src.crossposting.constants import Channel
from src.crossposting.service import (
    get_next_meme_for_tgchannelen,
    get_next_meme_for_tgchannelru,
    log_meme_sent,
)
from src.storage.constants import MemeStatus, MemeType
from src.storage.schemas import MemeData
from src.storage.service import update_meme
from src.storage.upload import download_meme_content_from_tg
from src.tgbot.bot import bot
from src.tgbot.constants import (
    TELEGRAM_CHANNEL_EN_CHAT_ID,
    TELEGRAM_CHANNEL_RU_CHAT_ID,
)
from src.tgbot.handlers.chat.explain_meme import call_chatgpt_vision
from src.tgbot.senders.meme import send_new_message_with_meme
from src.tgbot.senders.utils import get_random_emoji


def _get_caption_for_crossposting_meme(meme: MemeData, channel: Channel) -> str:
    caption = escape(meme.caption, quote=False) if meme.caption else ""

    ref_link = "https://t.me/ffmemesbot?start=sc_{}_{}".format(meme.id, channel.value)
    emoji = get_random_emoji()
    referral_html = f"""{emoji} <i><a href="{ref_link}">Fast Food Memes</a></i>"""

    return caption + "\n\n" + referral_html


async def get_caption_for_crossposting_meme(meme: MemeData, channel: Channel) -> str:
    logger = get_run_logger()

    if meme.type != MemeType.IMAGE:
        return _get_caption_for_crossposting_meme(meme, channel)

    # explain meme
    try:
        prompt = """
Мама прислала тебе эту смешную картинку. Объясни двумя предложениями, в чем прикол.
Не пересказывай содержание мема и используй неформальную лексику.
        """
        if meme.caption:
            prompt += f"Под мемом была подпись: {meme.caption}"

        image_bytes = await download_meme_content_from_tg(meme.telegram_file_id)
        vision_result = await call_chatgpt_vision(image_bytes, prompt=prompt)

        if vision_result:
            ref_link = "https://t.me/ffmemesbot?start=sc_{}_{}".format(
                meme.id, channel.value
            )
            emoji = get_random_emoji()
            return f"""
{emoji} <i><a href="{ref_link}">@ffmemesbot:</a></i> {vision_result}
            """

    except Exception as e:
        logger.warning(f"Failed to explain meme {meme.id}: {e}")
        return _get_caption_for_crossposting_meme(meme, channel)


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
        bot, TELEGRAM_CHANNEL_EN_CHAT_ID, next_meme, reply_markup=None
    )

    await log_meme_sent(next_meme.id, Channel.TG_CHANNEL_EN)
    await update_meme(next_meme.id, status=MemeStatus.PUBLISHED)


@flow
async def post_meme_to_tgchannelru():
    logger = get_run_logger()

    meme_data = await get_next_meme_for_tgchannelru()
    next_meme = MemeData(**meme_data)
    logger.info(f"Next meme for TG Channel RU: {next_meme.id}")

    next_meme.caption = await get_caption_for_crossposting_meme(
        next_meme, Channel.TG_CHANNEL_RU
    )

    await send_new_message_with_meme(
        bot, TELEGRAM_CHANNEL_RU_CHAT_ID, next_meme, reply_markup=None
    )

    await log_meme_sent(next_meme.id, Channel.TG_CHANNEL_RU)
    await update_meme(next_meme.id, status=MemeStatus.PUBLISHED)
