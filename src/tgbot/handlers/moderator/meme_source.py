from telegram import Update, Bot
from telegram.ext import (
    ContextTypes, 
)

from src.tgbot.service import (
    update_meme_source, 
    get_or_create_meme_source,
    get_user_by_id,
)

from src.tgbot.senders.keyboards import (
    meme_source_language_selection_keyboard, 
    meme_source_change_status_keyboard,
)

from src.storage.constants import MemeSourceType, MemeSourceStatus
from src.tgbot.constants import UserType


async def handle_meme_source_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TODO: check that a user is moderator

    url = update.message.text.strip().lower()
    if "https://t.me/" in url:
        meme_source_type = MemeSourceType.TELEGRAM
    elif "https://vk.com/" in url:
        meme_source_type = MemeSourceType.VK
    else:  
        await update.message.reply_text("Unsupported meme source")
        return 
    
    meme_source = await get_or_create_meme_source(
        url=url,
        type=meme_source_type,
        status=MemeSourceStatus.IN_MODERATION,
        added_by=update.effective_user.id,
    )

    await meme_source_admin_pipeline(meme_source, update.effective_user.id, context.bot)
    

async def handle_meme_source_language_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    args = update.callback_query.data.split(":")
    meme_source_id, lang_code = int(args[1]), args[3]

    meme_source = await update_meme_source(meme_source_id, language_code=lang_code)
    if meme_source is None:
        await update.callback_query.answer("Meme source not found")
        return
    
    await update.callback_query.answer(f"Meme source lang is {lang_code} now")  
    await meme_source_admin_pipeline(meme_source, update.effective_user.id, context.bot)


async def handle_meme_source_change_status(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    args = update.callback_query.data.split(":")
    meme_source_id, status = int(args[1]), args[3]

    user = await get_user_by_id(update.effective_user.id)
    if user is None or user["type"] != UserType.MODERATOR:
        await update.callback_query.answer("🤷‍♀️ Only moderators can change meme source status 🤷‍♂️")
        return

    meme_source = await update_meme_source(meme_source_id, status=status)
    if meme_source is None:
        await update.callback_query.answer(f"Meme source {meme_source_id} not found")
        return
    
    await update.callback_query.answer(f"Meme source status is {status} now")  
    await meme_source_admin_pipeline(meme_source, update.effective_user.id, context.bot)


def _get_meme_source_info(meme_source: dict) -> str:
    return f"""
id: {meme_source["id"]}
url: {meme_source["url"]}
type: {meme_source["type"]}
language: {meme_source["language_code"]}
status: {meme_source["status"]}
added by: {meme_source["added_by"]}
    """


async def meme_source_admin_pipeline(
    meme_source: dict,
    user_id: int,
    bot: Bot,
) -> None:
    if meme_source["language_code"] is None:
        await bot.send_message(
            chat_id=user_id,
            text=f"""{_get_meme_source_info(meme_source)}\nPlease select a language for {meme_source["url"]}""",
            reply_markup=meme_source_language_selection_keyboard(meme_source_id=meme_source["id"]),
            disable_web_page_preview=True,
        )
        return

    await bot.send_message(
        chat_id=user_id,
        text=_get_meme_source_info(meme_source),
        disable_web_page_preview=True,
        reply_markup=meme_source_change_status_keyboard(meme_source["id"])
    )

    # TODO: buttons to change status