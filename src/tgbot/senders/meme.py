from typing import Tuple

from telegram import (
    InlineKeyboardMarkup,
    InputMediaAnimation,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)
from telegram.constants import ParseMode

from src.storage.constants import MemeType
from src.storage.schemas import MemeData
from src.tgbot.bot import bot


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
        caption = await get_meme_caption_for_user_id(meme, user_id)
        if meme.type == MemeType.IMAGE:
            input_media = InputMediaPhoto(
                media=meme.telegram_file_id,
                parse_mode=ParseMode.HTML,
                caption=caption,
            )
        elif meme.type == MemeType.VIDEO:
            input_media = InputMediaVideo(
                media=meme.telegram_file_id,
                parse_mode=ParseMode.HTML,
                caption=caption,
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
    user_id: int,
    meme: MemeData,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message:
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
        return await bot.send_video(
            chat_id=user_id,
            animation=meme.telegram_file_id,
            caption=meme.caption,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
        )
    else:
        raise NotImplementedError(f"Can't send meme. Unknown meme type: {meme.type}")


async def edit_last_message_with_meme(
    user_id: int,
    message_id: int,
    meme: MemeData,
    reply_markup: InlineKeyboardMarkup | None = None,
):
    await bot.edit_message_media(
        chat_id=user_id,
        message_id=message_id,
        media=get_input_media(meme),
        reply_markup=reply_markup,
    )

    # INFO: current TG BOT API doesn't support media + caption edit
    # in 1 API call. Also edit_message_media clears caption.
    # So we need to make 2 API calls...

    await bot.edit_message_caption(
        chat_id=user_id,
        message_id=message_id,
        caption=meme.caption,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
    )
