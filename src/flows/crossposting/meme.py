from html import escape

from prefect import flow, get_run_logger
from telegram.constants import ParseMode

from src.crossposting.constants import Channel
from src.crossposting.service import (
    get_next_meme_for_tgchannelen,
    get_next_meme_for_tgchannelru,
    log_meme_sent,
)
from src.storage.constants import MemeStatus
from src.storage.schemas import MemeData
from src.storage.service import update_meme
from src.tgbot.bot import bot
from src.tgbot.constants import (
    TELEGRAM_CHANNEL_EN_CHAT_ID,
    TELEGRAM_CHANNEL_EN_LINK,
    TELEGRAM_CHANNEL_RU_CHAT_ID,
    TELEGRAM_CHANNEL_RU_LINK,
)
from src.tgbot.handlers.treasury.constants import PAYOUTS, TrxType
from src.tgbot.handlers.treasury.payments import pay_if_not_paid
from src.tgbot.handlers.upload.service import get_meme_uploader_user_id
from src.tgbot.senders.meme import send_new_message_with_meme
from src.tgbot.senders.utils import get_random_emoji

# when we tried to explain meme in the post caption
# we received lots of negative feedback from users
# and number of post shares decreased significantly


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
    msg = await send_new_message_with_meme(
        bot, TELEGRAM_CHANNEL_EN_CHAT_ID, next_meme, reply_markup=None
    )

    await log_meme_sent(next_meme.id, Channel.TG_CHANNEL_EN)
    await update_meme(next_meme.id, status=MemeStatus.PUBLISHED)

    uploader_user_id = await get_meme_uploader_user_id(next_meme.id)
    if uploader_user_id:
        balance = await pay_if_not_paid(
            uploader_user_id, TrxType.MEME_PUBLISHED, next_meme.id
        )
        if balance:
            link = TELEGRAM_CHANNEL_EN_LINK + "/" + str(msg.message_id)
            await bot.send_message(
                uploader_user_id,
                f"""
/b: +<b>{PAYOUTS[TrxType.MEME_PUBLISHED]}</b> 🍔 because we <a href="{link}">posted your meme in our channel</a>.
                """,  # noqa
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )


@flow
async def post_meme_to_tgchannelru():
    logger = get_run_logger()

    meme_data = await get_next_meme_for_tgchannelru()
    next_meme = MemeData(**meme_data)
    logger.info(f"Next meme for TG Channel RU: {next_meme.id}")

    next_meme.caption = _get_caption_for_crossposting_meme(
        next_meme, Channel.TG_CHANNEL_RU
    )

    msg = await send_new_message_with_meme(
        bot, TELEGRAM_CHANNEL_RU_CHAT_ID, next_meme, reply_markup=None
    )

    await log_meme_sent(next_meme.id, Channel.TG_CHANNEL_RU)
    await update_meme(next_meme.id, status=MemeStatus.PUBLISHED)

    uploader_user_id = await get_meme_uploader_user_id(next_meme.id)
    if uploader_user_id:
        balance = await pay_if_not_paid(
            uploader_user_id, TrxType.MEME_PUBLISHED, next_meme.id
        )
        if balance:
            link = TELEGRAM_CHANNEL_RU_LINK + "/" + str(msg.message_id)
            await bot.send_message(
                uploader_user_id,
                f"""
/b: +<b>{PAYOUTS[TrxType.MEME_PUBLISHED]}</b> 🍔 за то, что мы <a href="{link}">запостили твой мем к себе в канал</a>.
                """,  # noqa
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
