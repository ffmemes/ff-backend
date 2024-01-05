
from telegram import Message

from src.tgbot import bot

from src.storage.constants import MemeType
from src.storage.schemas import MemeData

from src.tgbot.senders.keyboards import meme_reaction_keyboard
from src.recommendations.service import create_user_meme_reaction


# TODO: remove MemeData serialization for less CPU load?
async def send_meme(user_id: int, meme: MemeData) -> Message:
    # IDEA: add link to our bot?
    # IDEA: don't use captions at all

    if meme.type == MemeType.IMAGE:
        msg = await bot.application.bot.send_photo(
            chat_id=user_id, 
            photo=meme.telegram_file_id,
            caption=meme.caption,
            reply_markup=meme_reaction_keyboard(meme.id),
        )

    elif meme.type == MemeType.VIDEO:
        msg = await bot.application.bot.send_video(
            chat_id=user_id, 
            video=meme.telegram_file_id,
            caption=meme.caption,
            reply_markup=meme_reaction_keyboard(meme.id),
        )

    elif meme.type == MemeType.ANIMATION:
        msg = await bot.application.bot.send_video(
            chat_id=user_id, 
            animation=meme.telegram_file_id,
            caption=meme.caption,
            reply_markup=meme_reaction_keyboard(meme.id),
        )

    else:
        raise NotImplementedError(f"Can't send meme. Unknown meme type: {meme.type}")
    
    await create_user_meme_reaction(user_id, meme.id, meme.recommended_by)
    
    return msg

