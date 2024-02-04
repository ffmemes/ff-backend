import asyncio

from prefect import flow, get_run_logger

from src.broadcasts.service import get_users_which_were_active_hours_ago
from src.recommendations.meme_queue import check_queue, get_next_meme_for_user
from src.recommendations.service import create_user_meme_reaction
from src.tgbot.senders.meme import send_new_message_with_meme


@flow
async def broadcast_memes_to_users_active_hours_ago(hours: int = 48):
    """
    Runs each hour:
    1. Takes users which were active (hours, hours-1) hours ago
    2. Sends them a best meme
    """
    logger = get_run_logger()

    # TODO: better user retention strategy
    users = await get_users_which_were_active_hours_ago(hours)
    logger.info(f"Found {len(users)} users which were active {hours} hours ago.")

    # for all users, ensure we have a meme to send
    await asyncio.gather(*[check_queue(user["id"]) for user in users])

    for user in users:
        user_id = user["id"]
        # TODO: better strategy for choosing a meme for push

        meme = await get_next_meme_for_user(user_id)

        await send_new_message_with_meme(user_id, meme)
        await create_user_meme_reaction(user_id, meme.id, meme.recommended_by)
        await asyncio.sleep(0.1)  # flood control
