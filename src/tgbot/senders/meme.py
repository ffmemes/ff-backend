from typing import Tuple

from telegram import (
    Bot,
    InlineKeyboardMarkup,
    InputMediaAnimation,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)
from telegram.constants import ParseMode
from telegram.error import Forbidden

from src.recommendations.service import create_user_meme_reaction
from src.storage.constants import MemeType
from src.storage.schemas import MemeData
from src.tgbot.bot import bot
from src.tgbot.constants import UserType
from src.tgbot.senders.keyboards import meme_reaction_keyboard
from src.tgbot.senders.meme_caption import get_meme_caption_for_user_id
from src.tgbot.service import update_user
from src.tgbot.user_info import get_user_info


async def send_meme_to_user(bot: Bot, user_id: int, meme: MemeData):
    user_info = await get_user_info(user_id)
    reply_markup = meme_reaction_keyboard(meme.id, user_id)
    meme.caption = await get_meme_caption_for_user_id(meme, user_id, user_info)

    await send_new_message_with_meme(bot, user_id, meme, reply_markup)
    await create_user_meme_reaction(user_id, meme.id, meme.recommended_by)


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


async def send_album_with_memes(
    user_id: int,
    memes: list[MemeData],
) -> Tuple[Message]:
    media = []
    for meme in memes:
        if meme.type == MemeType.IMAGE:
            input_media = InputMediaPhoto(
                media=meme.telegram_file_id,
                parse_mode=ParseMode.HTML,
                caption=meme.caption,
            )
        elif meme.type == MemeType.VIDEO:
            input_media = InputMediaVideo(
                media=meme.telegram_file_id,
                parse_mode=ParseMode.HTML,
                caption=meme.caption,
            )
        elif meme.type == MemeType.ANIMATION:
            raise NotImplementedError("Can't send animation in album")
        else:
            raise NotImplementedError(
                f"Can't send meme. Unknown meme type: {meme.type}"
            )
        media.append(input_media)

    return await bot.send_media_group(
        chat_id=user_id,
        media=media,
    )


async def send_new_message_with_meme(
    bot: Bot,
    user_id: int,
    meme: MemeData,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message:
    try:
        if meme.type == MemeType.IMAGE:
            return await bot.send_photo(
                chat_id=user_id,
                photo=meme.telegram_file_id,
                caption=meme.caption,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
        elif meme.type == MemeType.VIDEO:
            return await bot.send_video(
                chat_id=user_id,
                video=meme.telegram_file_id,
                caption=meme.caption,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
        elif meme.type == MemeType.ANIMATION:
            return await bot.send_animation(
                chat_id=user_id,
                animation=meme.telegram_file_id,
                caption=meme.caption,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
        else:
            raise NotImplementedError(
                f"Can't send meme. Unknown meme type: {meme.type}"
            )
    except Forbidden:
        await update_user(user_id, type=UserType.BLOCKED_BOT)


async def edit_last_message_with_meme(
    message: Message,
    meme: MemeData,
    reply_markup: InlineKeyboardMarkup | None = None,
):
    await message.edit_media(
        media=get_input_media(meme),
        reply_markup=reply_markup,
    )

    # INFO: current TG BOT API doesn't support media + caption edit
    # in 1 API call. Also edit_message_media clears caption.
    # So we need to make 2 API calls...

    await message.edit_caption(
        caption=meme.caption,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
    )
