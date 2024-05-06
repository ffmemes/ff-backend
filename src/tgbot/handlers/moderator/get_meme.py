"""
    Handle /meme <meme_id> admin/mod command
"""

import asyncio

from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes,
)

from src.storage.schemas import MemeData
from src.tgbot.constants import UserType
from src.tgbot.senders.meme import send_album_with_memes, send_new_message_with_meme
from src.tgbot.service import get_meme_by_id, get_meme_source_by_id, get_meme_stats
from src.tgbot.user_info import get_user_info


async def send_meme_info(bot: Bot, update: Update, meme_id: int):
    meme_data = await get_meme_by_id(meme_id)
    if meme_data is None:
        await update.message.reply_text(f"Meme #{meme_id} not found")
        return

    if meme_data["telegram_file_id"] is None:
        await update.message.reply_text(
            f"""
Meme #{meme_id} wasn't uploaded to telegram.
Status: {meme_data['status']}
        """
        )
        return

    meme_source = await get_meme_source_by_id(meme_data["meme_source_id"])

    info = f"""
Meme #{meme_id}
- status: {meme_data["status"]}
- lang: {meme_data["language_code"]}
- published: {meme_data["published_at"]}
- source: #{meme_data["meme_source_id"]} / {meme_source["language_code"]}
---- {meme_source["url"]}
"""

    if meme_data["duplicate_of"]:
        info += f"""- duplicate of: #{meme_data["duplicate_of"]}\n"""

    if meme_data["caption"]:
        info += f"""- caption: {meme_data["caption"]}"""

    meme_stats = await get_meme_stats(meme_id)
    if meme_stats:
        info += f"""
Stats:
- likes: {meme_stats['nlikes']}
- dislikes: {meme_stats['ndislikes']}
- sent times: {meme_stats['nmemes_sent']}
- age days: {meme_stats['age_days']}
- rank in source: {meme_stats['raw_impr_rank']}/4
"""

    meme_data["caption"] = info
    meme = MemeData(**meme_data)
    reply_markup = None  # TODO: add buttons to change status
    return await send_new_message_with_meme(
        bot,
        update.effective_user.id,
        meme,
        reply_markup,
    )


async def handle_get_meme(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends you the meme by it's id"""
    user = await get_user_info(update.effective_user.id)
    if UserType(user["type"]).is_moderator is not True:
        return

    message_split = update.message.text.split()
    if len(message_split) < 2:
        await update.message.reply_text(
            "Please specify a <code>meme_id</code>", parse_mode=ParseMode.HTML
        )
        return

    try:
        meme_ids = [int(i) for i in message_split[1:]]
    except ValueError:
        await update.message.reply_text(
            "Please specify a valid <code>meme_id</code> (a number!)",
            parse_mode=ParseMode.HTML,
        )
        return

    if len(meme_ids) == 1:
        return await send_meme_info(context.bot, update, meme_ids[0])

    memes_data = await asyncio.gather(
        *[get_meme_by_id(meme_id) for meme_id in meme_ids]
    )
    memes = [
        MemeData(**meme)
        for meme in memes_data
        if meme is not None and meme["telegram_file_id"] is not None
    ]
    if len(memes) == 0:
        await update.message.reply_text(
            "Not a single meme you've provided had been found. Check your meme ids."
        )
        return

    # divide memes in batches of up to 10
    for i in range(0, len(memes), 10):
        await send_album_with_memes(update.effective_user.id, memes[i : i + 10])
