from html import escape

from telegram import Update
from telegram.constants import MessageEntityType
from telegram.ext import (
    ContextTypes,
)

from src.storage.schemas import MemeData
from src.tgbot.constants import TELEGRAM_CHANNEL_RU_CHAT_ID, UserType
from src.tgbot.logs import log
from src.tgbot.service import get_meme_by_id
from src.tgbot.user_info import get_user_info
from src.tgbot.utils import check_if_user_chat_member


async def handle_forwarded_from_tgchannelru(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Sends you the meme by it's id"""
    user = await get_user_info(update.effective_user.id)
    if user["type"] != UserType.ADMIN:
        return

    await log(f"Forwarded from tgchannelru: {escape(str(update.message.to_dict()))}")

    ces = update.message.caption_entities
    urls = [ce.url for ce in ces if ce.type == MessageEntityType.TEXT_LINK]
    if len(urls) != 1:
        return await update.message.reply_text(
            f"Can't parse caption: {escape(str(update.message.to_dict()))}"
        )

    url = urls[0]
    meme_id_str = url.replace("https://t.me/ffmemesbot?start=sc_", "").split("_")[0]
    if not meme_id_str.isdigit():
        return await update.message.reply_text(
            f"Can't parse meme_id from caption: {escape(str(update.message.to_dict()))}"
        )

    meme_id = int(meme_id_str)
    meme_data = await get_meme_by_id(meme_id)
    if not meme_data:
        return await update.message.reply_text(f"Meme not found by id: {meme_id}")

    meme = MemeData(**meme_data)

    await log(f"Meme_id: {meme.id}")

    users = []

    for user in users:
        if_user_in_channel = await check_if_user_chat_member(
            user, TELEGRAM_CHANNEL_RU_CHAT_ID
        )
        if if_user_in_channel:
            # TODO: log user in channel
            continue  # user already in channel -> probaby watched the meme

    # TODO:
    # 0. extract meme_id from caption
    # 1. select users with language ru
    # 2. select users who don't follow the channel (maybe check one by one)
    # 3. select users who didn't watch the meme
