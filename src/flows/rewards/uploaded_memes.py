import asyncio
from datetime import datetime

import telegram
from prefect import flow, get_run_logger

from src.crossposting.constants import Channel
from src.crossposting.service import (
    log_meme_sent,
)
from src.flows.rewards.service import (
    get_all_uploaded_memes_weekly_en,
    get_all_uploaded_memes_weekly_ru,
)
from src.storage.constants import MemeStatus
from src.storage.service import update_meme
from src.tgbot.bot import bot
from src.tgbot.constants import (
    TELEGRAM_CHANNEL_EN_CHAT_ID,
    TELEGRAM_CHANNEL_EN_LINK,
    TELEGRAM_CHANNEL_RU_CHAT_ID,
    TELEGRAM_CHANNEL_RU_LINK,
)
from src.tgbot.handlers.treasury.constants import TrxType
from src.tgbot.handlers.treasury.payments import pay_if_not_paid_with_alert
from src.tgbot.logs import log

"""
    1. Get all uploaded memes this week.
    2. Calculate some stats:
       - uploaded memes
       - users who uploaded memes
       - total views
       - average like %
    3. Get top 5 memes by like %.
    4. Reward users:
       - 500 🍔 for 1st plac
       - 300 🍔 for 2nd plac
       - 200 🍔 for 3rd plac
       - 100 🍔 for 4th plac
       - 50 🍔 for 5th plac
    5. Notify users about rewards:
       - send message to a channel with top 5 memes.
       - for meme authors which doesn't follow the channel,
         send a message with a link to the post in channel.
         with stats of user's uploaded memes
"""


@flow(name="Reward RU users for weekly top uploaded memes")
async def reward_ru_users_for_weekly_top_uploaded_memes():
    logger = get_run_logger()
    logger.info("Going to reward users for weekly top uploaded memes")

    uploaded_memes = await get_all_uploaded_memes_weekly_ru()
    logger.info(f"Received {len(uploaded_memes)} uploaded memes")

    if len(uploaded_memes) < 5:
        await log("Not enough memes to reward users: only {len(uploaded_memes)}")
        return

    nuploaded = len(uploaded_memes)
    nusers = len(set(m["author_id"] for m in uploaded_memes))
    views = sum(m["nmemes_sent"] for m in uploaded_memes)
    likes = sum(m["nlikes"] for m in uploaded_memes)
    dislikes = sum(m["ndislikes"] for m in uploaded_memes)
    avg_like = likes / (likes + dislikes) if likes + dislikes > 0 else 0

    logger.info(f"Uploaded: {nuploaded} by {nusers}, views: {views}, like%: {avg_like}")
    today = datetime.today().date().strftime("%Y-%m-%d")

    ###########################
    # reward top authors

    top_memes = sorted(
        uploaded_memes,
        key=lambda m: m["nlikes"] / (m["nlikes"] + m["ndislikes"])
        if m["nlikes"] + m["ndislikes"] > 0
        else 0,
        reverse=True,
    )[:5]

    for i, top_meme in enumerate(top_memes):
        if i == 0:
            type = TrxType.UPLOADER_TOP_WEEKLY_1
        elif i == 1:
            type = TrxType.UPLOADER_TOP_WEEKLY_2
        elif i == 2:
            type = TrxType.UPLOADER_TOP_WEEKLY_3
        elif i == 3:
            type = TrxType.UPLOADER_TOP_WEEKLY_4
        elif i == 4:
            type = TrxType.UPLOADER_TOP_WEEKLY_5
        else:
            continue

        await pay_if_not_paid_with_alert(
            bot,
            top_meme["author_id"],
            type,
            external_id=today,
        )

        if top_meme["status"] != MemeStatus.PUBLISHED:
            await update_meme(top_meme["meme_id"], status=MemeStatus.PUBLISHED)
            await log_meme_sent(top_meme["meme_id"], channel=Channel.TG_CHANNEL_RU)

    # send message to tgchannelru

    channel_text = f"""
🏆 <code>ТОП-5 загруженных мемов недели</code>

🥇 - {top_memes[0]["nickname"] or '???'}
🥈 - {top_memes[1]["nickname"] or '???'}
🥉 - {top_memes[2]["nickname"] or '???'}
🏅 - {top_memes[3]["nickname"] or '???'}
🏅 - {top_memes[4]["nickname"] or '???'}

📥 Загружено мемов: <b>{nuploaded}</b>
👤 Пользователями: <b>{nusers}</b>
👁️ Просмотры: <b>{views}</b>
👍 Доля лайков: <b>{round(likes * 100. / (likes + dislikes))}%</b>

Перешли топ мем в бота → <a href="https://t.me/ffmemesbot?start=kitchen">выиграй до 500 🍔</a>
    """  # noqa

    ms = await bot.send_media_group(
        TELEGRAM_CHANNEL_RU_CHAT_ID,
        [telegram.InputMediaPhoto(media=m["telegram_file_id"]) for m in top_memes],
        caption=channel_text,
        parse_mode="HTML",
    )

    message_link = f"{TELEGRAM_CHANNEL_RU_LINK}/{ms[0].id}"

    # send message to authors

    author_ids = set(m["author_id"] for m in top_memes)
    logger.info(f"Going to notify {len(author_ids)} authors about rewards")
    for author_id in author_ids:
        user_uploaded_memes = [m for m in uploaded_memes if m["author_id"] == author_id]
        likes = sum(m["nlikes"] for m in user_uploaded_memes)
        dislikes = sum(m["ndislikes"] for m in user_uploaded_memes)
        like_prc = round(likes * 100.0 / (likes + dislikes))
        views = sum(m["nmemes_sent"] for m in uploaded_memes)

        user_text = f"""
Стата по загруженным тобой мемам:
📥 Загружено мемов: {len(user_uploaded_memes)}
👁️ Просмотры: {views}
👍 Доля лайков: {like_prc}%

Смотри топ-5 мемов недели в нашем канале: {message_link}
        """
        try:
            await bot.send_message(author_id, user_text)
        except Exception as e:
            logger.error(f"Failed to send message to {author_id}: {e}")

        await asyncio.sleep(2)


@flow(name="Reward EN users for weekly top uploaded memes")
async def reward_en_users_for_weekly_top_uploaded_memes():
    logger = get_run_logger()
    logger.info("Going to reward users for weekly top uploaded memes")

    uploaded_memes = await get_all_uploaded_memes_weekly_en()
    logger.info(f"Received {len(uploaded_memes)} uploaded memes")

    if len(uploaded_memes) < 5:
        await log("Not enough memes to reward users: only {len(uploaded_memes)}")
        return

    nuploaded = len(uploaded_memes)
    nusers = len(set(m["author_id"] for m in uploaded_memes))
    views = sum(m["nmemes_sent"] for m in uploaded_memes)
    likes = sum(m["nlikes"] for m in uploaded_memes)
    dislikes = sum(m["ndislikes"] for m in uploaded_memes)
    avg_like = likes / (likes + dislikes) if likes + dislikes > 0 else 0

    logger.info(f"Uploaded: {nuploaded} by {nusers}, views: {views}, like%: {avg_like}")
    today = datetime.today().date().strftime("%Y-%m-%d")

    ###########################
    # reward top authors

    top_memes = sorted(
        uploaded_memes,
        key=lambda m: m["nlikes"] / (m["nlikes"] + m["ndislikes"])
        if m["nlikes"] + m["ndislikes"] > 0
        else 0,
        reverse=True,
    )[:5]

    for i, top_meme in enumerate(top_memes):
        if i == 0:
            type = TrxType.UPLOADER_TOP_WEEKLY_1
        elif i == 1:
            type = TrxType.UPLOADER_TOP_WEEKLY_2
        elif i == 2:
            type = TrxType.UPLOADER_TOP_WEEKLY_3
        elif i == 3:
            type = TrxType.UPLOADER_TOP_WEEKLY_4
        elif i == 4:
            type = TrxType.UPLOADER_TOP_WEEKLY_5
        else:
            continue

        await pay_if_not_paid_with_alert(
            bot,
            top_meme["author_id"],
            type,
            external_id=today,
        )

        if top_meme["status"] != MemeStatus.PUBLISHED:
            await update_meme(top_meme["meme_id"], status=MemeStatus.PUBLISHED)
            await log_meme_sent(top_meme["meme_id"], channel=Channel.TG_CHANNEL_EN)

    # send message to tgchannelen

    channel_text = f"""
🏆 <code>Best uploaded memes of a week</code>

🥇 - {top_memes[0]["nickname"] or '???'}
🥈 - {top_memes[1]["nickname"] or '???'}
🥉 - {top_memes[2]["nickname"] or '???'}
🏅 - {top_memes[3]["nickname"] or '???'}
🏅 - {top_memes[4]["nickname"] or '???'}

📥 uploaded memes: <b>{nuploaded}</b>
👤 by users: <b>{nusers}</b>
👁️ views: <b>{views}</b>
👍 like %: <b>{round(likes * 100. / (likes + dislikes))}%</b>

Forward top meme to our bot → <a href="https://t.me/ffmemesbot?start=kitchen">win up to 500 🍔</a>
    """  # noqa

    ms = await bot.send_media_group(
        TELEGRAM_CHANNEL_EN_CHAT_ID,
        [telegram.InputMediaPhoto(media=m["telegram_file_id"]) for m in top_memes],
        caption=channel_text,
        parse_mode="HTML",
    )

    message_link = f"{TELEGRAM_CHANNEL_EN_LINK}/{ms[0].id}"

    # send message to authors

    author_ids = set(m["author_id"] for m in top_memes)
    logger.info(f"Going to notify {len(author_ids)} authors about rewards")
    for author_id in author_ids:
        user_uploaded_memes = [m for m in uploaded_memes if m["author_id"] == author_id]
        likes = sum(m["nlikes"] for m in user_uploaded_memes)
        dislikes = sum(m["ndislikes"] for m in user_uploaded_memes)
        like_prc = round(likes * 100.0 / (likes + dislikes))
        views = sum(m["nmemes_sent"] for m in uploaded_memes)

        user_text = f"""
Your stats for uploaded memes:
📥 Uploaded memes: {len(user_uploaded_memes)}
👁️ Views: {views}
👍 Like %: {like_prc}%

Check out top-5 uploaded memes of the week in our channel: {message_link}
        """
        try:
            await bot.send_message(author_id, user_text)
        except Exception as e:
            logger.error(f"Failed to send message to {author_id}: {e}")

        await asyncio.sleep(2)
