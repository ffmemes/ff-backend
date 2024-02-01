import asyncio
from prefect import flow, get_run_logger

from src.broadcasts.service import get_users_which_were_active_hours_ago
from src.recommendations.meme_queue import get_next_meme_for_user, check_queue
from src.recommendations.service import create_user_meme_reaction
from src.tgbot.senders.meme import send_new_message_with_meme


@flow
async def broadcast_memes_to_users_active_hours_ago(hours=48):
    """
        Runs each hour:
        1. Takes users which were active (hours, hours-1) hours ago
        2. Sends them a best meme
    """
    logger = get_run_logger()

    users = await get_users_which_were_active_hours_ago()
    logger.info(f"Found {len(users)} users which were active {hours} hours ago.")

    for user in users:
        user_id = user["id"]
        # TODO: better strategy for choosing a meme for push

        await check_queue(user_id)
        meme = await get_next_meme_for_user(user_id)

        msg = await send_new_message_with_meme(user_id, meme)
        await create_user_meme_reaction(user_id, meme.id, meme.recommended_by)
        await asyncio.sleep(1)  # flood control
    

