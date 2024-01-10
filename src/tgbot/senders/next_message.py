from telegram import (
    Message, 
    Update, 
    InputMediaPhoto, 
    InputMediaVideo, 
    InputMediaAnimation,
)

from src.storage.schemas import MemeData
from src.storage.constants import MemeType

from src.tgbot import bot
from src.tgbot.constants import Reaction
from src.tgbot.senders.keyboards import meme_reaction_keyboard
from src.tgbot.senders.alerts import send_queue_preparing_alert
from src.tgbot.senders.meme import send_new_message_with_meme, get_input_media
from src.recommendations.service import create_user_meme_reaction
from src.recommendations.meme_queue import (
    get_next_meme_for_user,
)


def prev_update_can_be_edited_with_media(prev_update: Update) -> bool:
    if prev_update.callback_query is None: 
        return False  # triggered by a message from user 
    
    # user clicked on our message with buttons
    if prev_update.callback_query.message.effective_attachment is None:
        return False  # message without media
    
    # FIXME: sometimes message is too old and can't be edited.
    return True  # message from our bot & has media to be replaced


async def next_message(
    user_id: int,
    prev_update: Update,
    prev_reaction_id: int | None = None,
) -> Message:
    # TODO: achievements
    meme = await get_next_meme_for_user(user_id)
    if not meme:
        # TODO: also edit / delete
        return await send_queue_preparing_alert(user_id)
    
    send_new_message = prev_reaction_id is None or Reaction(prev_reaction_id).is_positive
    if not send_new_message and prev_update_can_be_edited_with_media(prev_update):
        msg = await prev_update.callback_query.message.edit_media(
            media=get_input_media(meme),
            reply_markup=meme_reaction_keyboard(meme.id),
        )
    else:
        msg = await send_new_message_with_meme(user_id, meme)

    await create_user_meme_reaction(user_id, meme.id, meme.recommended_by)
    return msg

