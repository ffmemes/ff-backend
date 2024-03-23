import asyncio
import logging
import random
from html import escape

from telegram import Message, Update
from telegram.constants import MessageEntityType
from telegram.error import BadRequest, Forbidden, RetryAfter
from telegram.ext import (
    ContextTypes,
)

from src.broadcasts.service import get_users_to_broadcast_meme_from_tgchannelru
from src.storage.schemas import MemeData
from src.tgbot.constants import TELEGRAM_CHANNEL_RU_CHAT_ID, UserType
from src.tgbot.logs import log
from src.tgbot.service import get_meme_by_id, update_user
from src.tgbot.user_info import get_user_info, update_user_info_cache
from src.tgbot.utils import check_if_user_chat_member


async def forward_message_to_user(
    message: Message,
    user_id: int,
) -> bool:
    try:
        await message.forward(user_id)
        return True
    except (BadRequest, Forbidden):
        logging.info(
            f"❌ Failed to forward: {user_id} blocked the bot",
        )
        await update_user(user_id, type=UserType.BLOCKED_BOT)
        await update_user_info_cache(user_id)
        return False
    except RetryAfter as e:
        logging.info(
            f"❌ Failed to forward: RetryAfter: {e.retry_after}",
        )
        await asyncio.sleep(e.retry_after + 1)
        return await forward_message_to_user(message, user_id)  # is it safe?
    except Exception as e:
        logging.warning(
            f"❌ Failed to forward to user_id: {e}",
        )
        return False


async def handle_forwarded_from_tgchannelru(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Receives a forward from tgchannelru
    And forwards it to all users who
    1. don't follow the channel
    2. hadn't seen this meme yet
    3. set language ru
    """
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
    users = await get_users_to_broadcast_meme_from_tgchannelru(meme.id)
    await log(f"Going to forward meme_id={meme.id} to {len(users)} users")

    users_received = 0
    random.shuffle(users)
    for user in users:
        user_id = user["user_id"]
        if_user_in_channel = await check_if_user_chat_member(
            context.bot,
            user_id,
            TELEGRAM_CHANNEL_RU_CHAT_ID,
        )
        if if_user_in_channel:
            continue  # user already in channel -> probaby watched the meme

        if await forward_message_to_user(update.message, user_id):
            users_received += 1

        if users_received % 100 == 0:
            await log(
                f"⏳ {users_received} users received forward with meme #{meme.id}"
            )

        await asyncio.sleep(0.5)

    await log(f"✅ {users_received} users received forward with meme: #{meme.id}")
