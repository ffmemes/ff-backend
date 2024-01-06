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
    
    return True  # message from our bot & has media to be replaced


def get_input_media(meme: MemeData) -> InputMediaPhoto | InputMediaVideo | InputMediaAnimation:
    if meme.type == MemeType.IMAGE:
        return InputMediaPhoto(
            media=meme.telegram_file_id,
            caption=meme.caption,
        )
    elif meme.type == MemeType.VIDEO:
        return InputMediaVideo(
            media=meme.telegram_file_id,
            caption=meme.caption,
        ) 
    elif meme.type == MemeType.ANIMATION:
        return InputMediaAnimation(
            media=meme.telegram_file_id,
            caption=meme.caption,
        )
    else:
        raise NotImplementedError(f"Can't send meme. Unknown meme type: {meme.type}")


async def next_message(
    user_id: int,
    prev_update: Update,
    prev_reaction_id: int | None,
) -> Message:
    # TODO: achievements
    meme = await get_next_meme_for_user(user_id)
    if not meme:
        # TODO: also edit / delete
        return await send_queue_preparing_alert(user_id)
    
    send_new_message = prev_reaction_id is None or Reaction(prev_reaction_id).is_positive
    print("send_new_message:", send_new_message)
    print("prev_update:", prev_update)
    print("prev_update_can_be_edited_with_media(prev_update): ", prev_update_can_be_edited_with_media(prev_update))
    if not send_new_message and prev_update_can_be_edited_with_media(prev_update):
        msg = await prev_update.callback_query.message.edit_media(
            media=get_input_media(meme),
            reply_markup=meme_reaction_keyboard(meme.id),
        )
    else:
        print("sending new message with meme")
        msg = await send_new_message_with_meme(user_id, meme)

    await create_user_meme_reaction(user_id, meme.id, meme.recommended_by)
    return msg


async def send_new_message_with_meme(
    user_id: int,
    meme: MemeData,
) -> Message:
    if meme.type == MemeType.IMAGE:        
        return await bot.application.bot.send_photo(
            chat_id=user_id, 
            photo=meme.telegram_file_id,
            caption=meme.caption,
            reply_markup=meme_reaction_keyboard(meme.id),
        )
    elif meme.type == MemeType.VIDEO: 
        return await bot.application.bot.send_video(
            chat_id=user_id, 
            video=meme.telegram_file_id,
            caption=meme.caption,
            reply_markup=meme_reaction_keyboard(meme.id),
        )
    elif meme.type == MemeType.ANIMATION:
        return await bot.application.bot.send_video(
            chat_id=user_id, 
            animation=meme.telegram_file_id,
            caption=meme.caption,
            reply_markup=meme_reaction_keyboard(meme.id),
        )
    
    else:
        raise NotImplementedError(f"Can't send meme. Unknown meme type: {meme.type}")
    