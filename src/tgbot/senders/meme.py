
from telegram import (
    Message, 
    Update, 
    InputMediaPhoto, 
    InputMediaVideo, 
    InputMediaAnimation,
)

from src.tgbot import bot

from src.storage.constants import MemeType
from src.storage.schemas import MemeData

from src.tgbot.senders.keyboards import meme_reaction_keyboard
from src.recommendations.service import create_user_meme_reaction


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