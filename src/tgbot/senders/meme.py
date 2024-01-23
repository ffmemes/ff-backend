from telegram import (
    Message,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaAnimation,
)
from telegram.constants import ParseMode

from src.tgbot import bot

from src.storage.constants import MemeType
from src.storage.schemas import MemeData

from src.tgbot.senders.keyboards import meme_reaction_keyboard
from src.recommendations.service import create_user_meme_reaction
from src.tgbot.senders.utils import get_meme_caption


def get_input_media(
    meme: MemeData,
) -> InputMediaPhoto | InputMediaVideo | InputMediaAnimation:
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
    meme_caption_with_referral_link = get_meme_caption(meme, user_id)
    if meme.type == MemeType.IMAGE:
        return await bot.application.bot.send_photo(
            chat_id=user_id,
            photo=meme.telegram_file_id,
            caption=meme_caption_with_referral_link,
            reply_markup=meme_reaction_keyboard(meme.id),
            parse_mode=ParseMode.HTML,
        )
    elif meme.type == MemeType.VIDEO:
        return await bot.application.bot.send_video(
            chat_id=user_id,
            video=meme.telegram_file_id,
            caption=meme_caption_with_referral_link,
            reply_markup=meme_reaction_keyboard(meme.id),
            parse_mode=ParseMode.HTML,
        )
    elif meme.type == MemeType.ANIMATION:
        return await bot.application.bot.send_video(
            chat_id=user_id,
            animation=meme.telegram_file_id,
            caption=meme_caption_with_referral_link,
            reply_markup=meme_reaction_keyboard(meme.id),
            parse_mode=ParseMode.HTML,
        )
    else:
        raise NotImplementedError(f"Can't send meme. Unknown meme type: {meme.type}")


async def edit_last_message_with_meme(
    user_id: int,
    meme_id: int,
    meme: MemeData,
):
    await bot.application.bot.edit_message_media(
        chat_id=user_id,
        message_id=meme_id,
        media=get_input_media(meme),
        reply_markup=meme_reaction_keyboard(meme.id),
    )
    meme_caption_with_referral_link = get_meme_caption(meme, user_id)
    await bot.application.bot.edit_message_caption(
        chat_id=user_id,
        message_id=meme_id,
        caption=meme_caption_with_referral_link,
        parse_mode=ParseMode.HTML,
        reply_markup=meme_reaction_keyboard(meme.id),
    )
