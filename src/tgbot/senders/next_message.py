import asyncio
import logging

from telegram import (
    Bot,
    Message,
    Update,
)
from telegram.error import BadRequest

from src.recommendations import meme_queue
from src.recommendations.service import (
    create_user_meme_reaction,
    user_meme_reaction_exists,
)
from src.storage.schemas import MemeData
from src.tgbot.constants import Reaction
from src.tgbot.senders.alerts import send_queue_preparing_alert
from src.tgbot.senders.keyboards import meme_reaction_keyboard
from src.tgbot.senders.meme import (
    edit_last_message_with_meme,
    send_new_message_with_meme,
)
from src.tgbot.senders.meme_caption import get_meme_caption_for_user_id
from src.tgbot.senders.popups import get_popup_to_send, send_popup
from src.tgbot.user_info import get_user_info


async def get_next_meme_for_user(
    user_id: int,
    max_attempts: int = 10,
) -> MemeData | None:
    for _ in range(max_attempts):
        meme = await meme_queue.get_next_meme_for_user(user_id)
        if meme and not await user_meme_reaction_exists(user_id, meme.id):
            return meme
        if not meme:
            await meme_queue.generate_recommendations(user_id, limit=7)

    logging.warning(
        f"Failed to find unseen meme for user {user_id} after {max_attempts} attempts"
    )
    return None


async def next_message(
    bot: Bot,
    user_id: int,
    prev_update: Update,
    prev_reaction_id: int | None = None,
) -> Message:
    user_info = await get_user_info(user_id)
    # TODO: if watched > 30 memes / day show paywall / tasks / donate

    popup = await get_popup_to_send(user_id, user_info)
    if popup:
        return await send_popup(user_id, popup)

    meme = await get_next_meme_for_user(user_id)
    if not meme:
        asyncio.create_task(meme_queue.check_queue(user_id))
        # TODO: also edit / delete previous message
        return await send_queue_preparing_alert(bot, user_id)

    reply_markup = meme_reaction_keyboard(meme.id, user_id)
    meme.caption = await get_meme_caption_for_user_id(meme, user_id, user_info)

    should_edit = (
        prev_reaction_id is not None
        and not Reaction(prev_reaction_id).is_positive
        and prev_update.callback_query
        and prev_update.callback_query.message.effective_attachment
    )

    if should_edit:
        try:
            msg = await edit_last_message_with_meme(
                prev_update.callback_query.message, meme, reply_markup
            )
        except BadRequest as e:
            logging.error(f"Failed to edit message: {e}")
            msg = await send_new_message_with_meme(bot, user_id, meme, reply_markup)
    else:
        try:
            msg = await send_new_message_with_meme(bot, user_id, meme, reply_markup)
        except BadRequest as e:
            logging.error(f"Failed to send new message: {e}")
            raise  # Re-raise the exception if sending a new message fails

    await create_user_meme_reaction(user_id, meme.id, meme.recommended_by)
    asyncio.create_task(meme_queue.check_queue(user_id))
    return msg
