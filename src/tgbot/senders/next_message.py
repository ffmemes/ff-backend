import asyncio

from telegram import (
    Message,
    Update,
)

from src.recommendations.meme_queue import check_queue, get_next_meme_for_user
from src.recommendations.service import (
    create_user_meme_reaction,
    user_meme_reaction_exists,
)
from src.tgbot.constants import Reaction
from src.tgbot.senders.achievements import send_achievement_if_needed
from src.tgbot.senders.alerts import send_queue_preparing_alert
from src.tgbot.senders.meme import (
    edit_last_message_with_meme,
    send_new_message_with_meme,
)


def prev_update_can_be_edited_with_media(prev_update: Update) -> bool:
    if prev_update.callback_query is None:
        return False  # triggered by a message from user

    # user clicked on our message with buttons
    if prev_update.callback_query.message.effective_attachment is None:
        return False  # message without media

    return True  # message from our bot & has media to be replaced


async def next_message(
    user_id: int,
    prev_update: Update,
    prev_reaction_id: int | None = None,
) -> Message:
    # TODO: if watched > 30 memes / day show paywall / tasks / donate

    await send_achievement_if_needed(user_id)

    while True:
        meme = await get_next_meme_for_user(user_id)
        if not meme:
            asyncio.create_task(check_queue(user_id))
            # TODO: also edit / delete
            return await send_queue_preparing_alert(user_id)

        exists = await user_meme_reaction_exists(user_id, meme.id)
        if not exists:  # this meme wasn't sent yet
            break

    send_new_message = (
        prev_reaction_id is None or Reaction(prev_reaction_id).is_positive
    )
    if not send_new_message and prev_update_can_be_edited_with_media(prev_update):
        msg = await edit_last_message_with_meme(
            user_id, prev_update.callback_query.message.id, meme
        )
    else:
        msg = await send_new_message_with_meme(user_id, meme)

    await create_user_meme_reaction(user_id, meme.id, meme.recommended_by)
    asyncio.create_task(check_queue(user_id))
    return msg
