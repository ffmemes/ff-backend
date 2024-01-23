from telegram import Update, Message
from telegram.constants import ParseMode

from src.storage.schemas import MemeData
from src.tgbot import bot


async def send_or_edit(
    prev_update: Update,
    text: str,
    reply_markup: dict,
) -> Message:
    if prev_update.callback_query is not None:
        return await prev_update.callback_query.message.edit_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

    return await prev_update.message.reply_text(
        text=text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


def get_meme_caption(meme: MemeData, user_id: int) -> str:
    """Formats meme caption to add the caption + referral link to the bot"""
    bot_username = bot.application.bot.username
    return (
        (f"{meme.caption}\n\n" if meme.caption else "")
        + f'<a href="https://t.me/{bot_username}?start=s_{user_id}_{meme.id}">FastFoodMemes</a>'
    )