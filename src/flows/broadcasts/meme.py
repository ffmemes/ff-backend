import asyncio

from prefect import flow, get_run_logger
from telegram import Bot

from src.broadcasts.service import (
    get_users_active_minutes_ago,
    get_users_active_more_than_days_ago,
)
from src.recommendations.meme_queue import check_queue, get_next_meme_for_user
from src.recommendations.service import create_user_meme_reaction
from src.storage.schemas import MemeData
from src.tgbot.bot import bot
from src.tgbot.senders.keyboards import meme_reaction_keyboard
from src.tgbot.senders.meme import send_new_message_with_meme
from src.tgbot.senders.meme_caption import get_meme_caption_for_user_id
from src.tgbot.user_info import get_user_info


async def send_meme_to_user(bot: Bot, user_id: int, meme: MemeData):
    user_info = await get_user_info(user_id)
    reply_markup = meme_reaction_keyboard(meme.id, user_id)
    meme.caption = await get_meme_caption_for_user_id(meme, user_id, user_info)

    await send_new_message_with_meme(bot, user_id, meme, reply_markup)
    await create_user_meme_reaction(user_id, meme.id, meme.recommended_by)


async def broadcast_next_meme_to_users(users):
    logger = get_run_logger()
    logger.info(f"Going to sent next meme to {len(users)} users")

    for user in users:
        user_id = user["id"]
        await check_queue(user_id)
        meme = await get_next_meme_for_user(user_id)
        if meme:
            await send_meme_to_user(bot, user_id, meme)
            logger.info(f"Sent meme_id={meme.id} to #{user_id}")
            await asyncio.sleep(0.2)  # flood control


@flow
async def broadcast_next_meme_to_active_15m_ago():
    users = await get_users_active_minutes_ago(15, 30)
    await broadcast_next_meme_to_users(users)


@flow
async def broadcast_next_meme_to_active_24h_ago():
    users = await get_users_active_minutes_ago(24 * 60, 24 * 60 + 60)
    await broadcast_next_meme_to_users(users)


@flow
async def broadcast_next_meme_to_active_48h_ago():
    users = await get_users_active_minutes_ago(48 * 60, 48 * 60 + 60)
    await broadcast_next_meme_to_users(users)


@flow
async def broadcast_next_meme_to_active_1w_ago():
    users = await get_users_active_minutes_ago(7 * 24 * 60, 7 * 24 * 60 + 60)
    await broadcast_next_meme_to_users(users)


@flow
async def broadcast_next_meme_to_active_4w_ago():
    users = await get_users_active_minutes_ago(4 * 7 * 24 * 60, 4 * 7 * 24 * 60 + 60)
    await broadcast_next_meme_to_users(users)


@flow
async def broadcast_next_meme_to_active_more_than_days_ago(days: int = 3):
    """To call manually sometimes"""
    users = await get_users_active_more_than_days_ago(days)
    await broadcast_next_meme_to_users(users)
