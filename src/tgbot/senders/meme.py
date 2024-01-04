
from telegram import Message

from src.tgbot import bot

from src.storage.constants import MemeType
from src.storage.schemas import MemeData

from src.tgbot.senders.keyboards import meme_reaction_keyboard


async def send_meme(user_id: int, meme: MemeData) -> Message:
    # IDEA: add link to our bot?
    # IDEA: don't use captions at all

    if meme.type == MemeType.IMAGE:
        msg = await bot.application.bot.send_photo(
            chat_id=user_id, 
            photo=meme.file_id,
            caption=meme.caption,
            reply_markup=meme_reaction_keyboard(meme.id),
        )

    elif meme.type == MemeType.VIDEO:
        msg = await bot.application.bot.send_video(
            chat_id=user_id, 
            video=meme.file_id,
            caption=meme.caption,
            reply_markup=meme_reaction_keyboard(meme.id),
        )

    elif meme.type == MemeType.ANIMATION:
        msg = await bot.application.bot.send_video(
            chat_id=user_id, 
            animation=meme.file_id,
            caption=meme.caption,
            reply_markup=meme_reaction_keyboard(meme.id),
        )

    else:
        raise NotImplementedError(f"Can't send meme. Unknown meme type: {meme.type}")
    
    return msg

