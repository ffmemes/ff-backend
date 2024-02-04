from telegram import Message, Update
from telegram.ext import (
    ContextTypes,
)

from src.flows.parsers.tg import parse_telegram_source
from src.flows.parsers.vk import parse_vk_source
from src.storage.constants import MemeSourceStatus, MemeSourceType
from src.tgbot.constants import UserType
from src.tgbot.logs import log
from src.tgbot.senders.keyboards import (
    meme_source_change_status_keyboard,
    meme_source_language_selection_keyboard,
)
from src.tgbot.senders.utils import send_or_edit
from src.tgbot.service import (
    get_or_create_meme_source,
    update_meme_source,
)
from src.tgbot.user_info import get_user_info


async def handle_meme_source_link(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user_info = await get_user_info(update.effective_user.id)
    if not UserType(user_info["type"]).is_moderator:
        return

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

    await meme_source_admin_pipeline(meme_source, update)


async def handle_meme_source_language_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user_id = update.effective_user.id
    user_info = await get_user_info(user_id)
    if not UserType(user_info["type"]).is_moderator:
        return

    args = update.callback_query.data.split(":")
    meme_source_id, lang_code = int(args[1]), args[3]

    meme_source = await update_meme_source(meme_source_id, language_code=lang_code)
    if meme_source is None:
        await update.callback_query.answer("Meme source not found")
        return

    await log(f"ℹ️ MemeSource ${meme_source_id}: set_lang={lang_code} (by {user_id})")

    await update.callback_query.answer(f"Meme source lang is {lang_code} now")
    await meme_source_admin_pipeline(meme_source, update)


async def handle_meme_source_change_status(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user_id = update.effective_user.id
    user_info = await get_user_info(user_id)
    if not UserType(user_info["type"]).is_moderator:
        await update.callback_query.answer(
            "🤷‍♀️ Only moderators can change meme source status 🤷‍♂️"
        )
        return

    args = update.callback_query.data.split(":")
    meme_source_id, status = int(args[1]), args[3]

    meme_source = await update_meme_source(meme_source_id, status=status)
    if meme_source is None:
        await update.callback_query.answer(f"Meme source {meme_source_id} not found")
        return

    await log(f"ℹ️ MemeSource ${meme_source_id}: set_status={status} (by {user_id})")

    await update.callback_query.answer(f"Meme source status is {status} now")
    await meme_source_admin_pipeline(meme_source, update)

    if status == MemeSourceStatus.PARSING_ENABLED:  # trigger parsing
        # TODO: async
        if meme_source["type"] == MemeSourceType.VK:
            await parse_vk_source(meme_source_id, meme_source["url"])
        elif meme_source["type"] == MemeSourceType.TELEGRAM:
            await parse_telegram_source(meme_source_id, meme_source["url"])


def _get_meme_source_info(meme_source: dict) -> str:
    return f"""
id: {meme_source["id"]}
url: {meme_source["url"]}
type: {meme_source["type"]}
language: {meme_source["language_code"]}
added by: {meme_source["added_by"]}
<b>status</b>: {meme_source["status"]}
    """


async def meme_source_admin_pipeline(
    meme_source: dict,
    update: Update,
) -> Message:
    ms_info = _get_meme_source_info(meme_source)
    if meme_source["language_code"] is None:
        return await send_or_edit(
            update,
            text=f"""{ms_info}\nPlease select a language for {meme_source["url"]}""",
            reply_markup=meme_source_language_selection_keyboard(
                meme_source_id=meme_source["id"]
            ),
        )

    return await send_or_edit(
        update,
        text=ms_info,
        reply_markup=meme_source_change_status_keyboard(meme_source["id"]),
    )
