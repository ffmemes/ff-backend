"""
    Handle /meme <meme_id> admin/mod command
"""

import asyncio

from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes,
)

from src import redis
from src.recommendations.meme_queue import get_next_meme_for_user
from src.recommendations.service import (
    filter_unseen_memes,
    get_user_reactions_for_meme_ids,
)
from src.storage.schemas import MemeData
from src.tgbot.constants import UserType
from src.tgbot.senders.meme import (
    send_album_with_memes,
    send_meme_to_user,
    send_new_message_with_meme,
)
from src.tgbot.service import (
    get_meme_by_id,
    get_meme_source_by_id,
    get_meme_stats,
)
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
        meme_ids = [int(i.replace(",", "").strip()) for i in message_split[1:]]
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


async def handle_show_memes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    команду /show, которая:

    1. принимает список meme_ids (через пробел или через запятые, аналогично /meme)
    2. выкидывает мемы:
    -- которые юзер уже видел
    -- которые юзер не мог увидеть из-за настроек языков
    -- у которых meme.type != "ok"

    3. очищает очередь мемов на показ в redis. Пример.
    4. загружает отфильтрованные мемы в очередь
    5. присылает первый мем из очереди юзеру.

    ВАЖНО:
    Перед тем, как показывать мемы, необходимо прислать статистику по указанным мемам:
    1. Сколько из них уже просмотрено (юзером, кто прислал команду)
    2. Сколько из них ты бы не мог посмотреть (из-за языка, meme.type)
    3. Среди просмотренных сколько лайков / дизлайков / % (ты поставил)
    4. Сколько новых мемов ты сейчас увидешь в очереди.

    Если после фильтрации осталось 0 мемов, то очередь не очищать, прислать текстом сообщение об этом.
    """

    user_id = update.effective_user.id
    user = await get_user_info(user_id)
    if UserType(user["type"]).is_moderator is not True:
        return

    message_split = update.message.text.split()
    if len(message_split) < 2:
        await update.message.reply_text(
            "USAGE: <code>/show meme_id1 meme_id2</code>", parse_mode=ParseMode.HTML
        )
        return

    try:
        meme_ids = list(set(int(i.replace(",", "").strip()) for i in message_split[1:]))
    except ValueError:
        await update.message.reply_text(
            "Please specify a valid <code>meme_id</code> (a number!)",
            parse_mode=ParseMode.HTML,
        )
        return

    unseen_memes = await filter_unseen_memes(user_id, meme_ids)
    if len(unseen_memes) == 0:
        report = "😷 Nothing to show: no unseen memes found"
    else:
        report = f"""Added to queue: {len(unseen_memes)} / {len(meme_ids)} memes"""

    seen_meme_ids = list(set(meme_ids) - set(meme["id"] for meme in unseen_memes))
    if len(seen_meme_ids) > 0:
        user_reactions = await get_user_reactions_for_meme_ids(user_id, seen_meme_ids)
        nlikes = sum(1 for r in user_reactions if r["reaction_id"] == 1)
        ndislikes = sum(1 for r in user_reactions if r["reaction_id"] == 2)
        report += f"\nSeen: {len(seen_meme_ids)} Likes: {nlikes}, dislikes: {ndislikes}"

    await update.message.reply_text(report)

    if len(unseen_memes) > 0:
        queue_key = redis.get_meme_queue_key(user_id)
        await redis.add_memes_to_queue_by_key(queue_key, unseen_memes)

        meme = await get_next_meme_for_user(user_id)
        await send_meme_to_user(context.bot, user_id, meme)
