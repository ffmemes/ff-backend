import asyncio

from prefect import flow, get_run_logger

from src.broadcasts.service import (
    get_user_ids_active_minutes_ago,
    get_users_active_more_than_days_ago,
)
from src.recommendations.meme_queue import check_queue, get_next_meme_for_user
from src.tgbot.bot import bot
from src.tgbot.senders.meme import send_meme_to_user


async def broadcast_next_meme_to_users(user_ids: list[int]):
    logger = get_run_logger()
    logger.info(f"Going to sent next meme to {len(user_ids)} users")

    for user_id in user_ids:
        await check_queue(user_id)
        meme = await get_next_meme_for_user(user_id)
        if meme:
            await send_meme_to_user(bot, user_id, meme)
            logger.info(f"Sent meme_id={meme.id} to #{user_id}")
            await asyncio.sleep(0.2)  # flood control


@flow
async def broadcast_next_meme_to_active_15m_ago():
    user_ids = await get_user_ids_active_minutes_ago(15, 30)
    await broadcast_next_meme_to_users(user_ids)


@flow
async def broadcast_next_meme_to_active_24h_ago():
    user_ids = await get_user_ids_active_minutes_ago(24 * 60, 24 * 60 + 60)
    await broadcast_next_meme_to_users(user_ids)


@flow
async def broadcast_next_meme_to_active_48h_ago():
    user_ids = await get_user_ids_active_minutes_ago(48 * 60, 48 * 60 + 60)
    await broadcast_next_meme_to_users(user_ids)


@flow
async def broadcast_next_meme_to_active_1w_ago():
    user_ids = await get_user_ids_active_minutes_ago(7 * 24 * 60, 7 * 24 * 60 + 60)
    await broadcast_next_meme_to_users(user_ids)


@flow
async def broadcast_next_meme_to_active_2w_ago():
    user_ids = await get_user_ids_active_minutes_ago(2 * 7 * 24 * 60, 2 * 7 * 24 * 60 + 60)
    await broadcast_next_meme_to_users(user_ids)


@flow
async def broadcast_next_meme_to_active_4w_ago():
    user_ids = await get_user_ids_active_minutes_ago(4 * 7 * 24 * 60, 4 * 7 * 24 * 60 + 60)
    await broadcast_next_meme_to_users(user_ids)


@flow
async def broadcast_next_meme_to_active_more_than_days_ago(days: int = 3):
    """To call manually sometimes"""
    user_ids = await get_users_active_more_than_days_ago(days)
    await broadcast_next_meme_to_users(user_ids)
