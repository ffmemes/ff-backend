from random import choice

from telegram import Update, Message
from telegram.constants import ParseMode

from src.storage.schemas import MemeData
from src.tgbot import bot


def get_random_emoji() -> str:
    return choice([
        "👉", "🤖", "🤣", "🌺", "🛠️", 
        "🐝", "🐌", "🦋", "🦧", "🦔", 
        "🍭", "🍿", "🎭", "🎲", "🏴‍☠️",
        "🃏", "💠", "🩵", "🔖", "🗞️", 
        "🧾", "🎐", "🪒", "🧫", "⚗️", 
        "🪪", "📟", "🖲️", "🛖", "🗺️", 
        "🚤", "🦼", "🪈", "🩰", "🏊🏻‍♂️", 
        "🤺", "🪂", "🥋", "🛼", "🥍", 
        "🪀", "🫗", "🦪", "🧆", "🫒", 
        "🪺", "🦩", "🦒", "🫎", "🪿", 
        "🧤", "🧖🏻‍♂️", "🧌", "🦿", "🍄",
    ])


def get_referral_link(user_id: int, meme_id: int) -> str:
    return f"https://t.me/{bot.application.bot.username}?start=s_{user_id}_{meme_id}"


def get_meme_caption(meme: MemeData, user_id: int) -> str:
    """ Adds referral link to meme caption """
    referral_html = f"""{get_random_emoji()} <a href="{get_referral_link(user_id, meme.id)}">Fast Food Memes</a>"""
    if meme.caption:
        return f"{meme.caption}\n\n{referral_html}"
    return referral_html


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
