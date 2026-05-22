import asyncio
from datetime import datetime

import telegram
from prefect import flow, get_run_logger

from src.crossposting.constants import Channel
from src.crossposting.service import (
    log_meme_sent,
)
from src.flows.hooks import notify_telegram_on_failure
from src.flows.rewards.service import (
    get_all_uploaded_memes_weekly_en,
    get_all_uploaded_memes_weekly_ru,
)
from src.storage.constants import MemeStatus, MemeType
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

REWARD_ALBUM_SCORE_VERSION = 0

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


def _meme_dict_to_input_media(m: dict):
    if m["type"] == MemeType.IMAGE:
        return telegram.InputMediaPhoto(media=m["telegram_file_id"])
    if m["type"] == MemeType.VIDEO:
        return telegram.InputMediaVideo(media=m["telegram_file_id"])
    if m["type"] == MemeType.ANIMATION:
        return telegram.InputMediaVideo(media=m["telegram_file_id"])
    raise Exception(f"Can't get meme type from: {m}")


REWARD_TRX_TYPES = (
    TrxType.UPLOADER_TOP_WEEKLY_1,
    TrxType.UPLOADER_TOP_WEEKLY_2,
    TrxType.UPLOADER_TOP_WEEKLY_3,
    TrxType.UPLOADER_TOP_WEEKLY_4,
    TrxType.UPLOADER_TOP_WEEKLY_5,
)


def _like_rate(meme: dict) -> float:
    reactions = meme["nlikes"] + meme["ndislikes"]
    return meme["nlikes"] / reactions if reactions > 0 else 0


def _like_percent(likes: int, dislikes: int) -> int:
    total = likes + dislikes
    return round(likes * 100.0 / total) if total else 0


def _top_uploaded_memes(uploaded_memes: list[dict], limit: int = 5) -> list[dict]:
    return sorted(uploaded_memes, key=_like_rate, reverse=True)[:limit]


def _ru_channel_text(
    top_memes: list[dict],
    *,
    uploaded_count: int,
    user_count: int,
    views: int,
    likes: int,
    dislikes: int,
) -> str:
    return f"""
🏆 <code>ТОП-5 загруженных мемов недели</code>

🥇 - {top_memes[0]["nickname"] or "???"}
🥈 - {top_memes[1]["nickname"] or "???"}
🥉 - {top_memes[2]["nickname"] or "???"}
🏅 - {top_memes[3]["nickname"] or "???"}
🏅 - {top_memes[4]["nickname"] or "???"}

📥 Загружено мемов: <b>{uploaded_count}</b>
👤 Пользователями: <b>{user_count}</b>
👁️ Просмотры: <b>{views}</b>
👍 Доля лайков: <b>{_like_percent(likes, dislikes)}%</b>

Перешли топ мем в бота → <a href="https://t.me/ffmemesbot?start=kitchen">выиграй до 500 🍔</a>
    """  # noqa


def _en_channel_text(
    top_memes: list[dict],
    *,
    uploaded_count: int,
    user_count: int,
    views: int,
    likes: int,
    dislikes: int,
) -> str:
    return f"""
🏆 <code>Best uploaded memes of a week</code>

🥇 - {top_memes[0]["nickname"] or "???"}
🥈 - {top_memes[1]["nickname"] or "???"}
🥉 - {top_memes[2]["nickname"] or "???"}
🏅 - {top_memes[3]["nickname"] or "???"}
🏅 - {top_memes[4]["nickname"] or "???"}

📥 uploaded memes: <b>{uploaded_count}</b>
👤 by users: <b>{user_count}</b>
👁️ views: <b>{views}</b>
👍 like %: <b>{_like_percent(likes, dislikes)}%</b>

Forward top meme to our bot → <a href="https://t.me/ffmemesbot?start=kitchen">win up to 500 🍔</a>
    """  # noqa


def _ru_user_text(
    user_uploaded_memes: list[dict],
    *,
    views: int,
    like_percent: int,
    message_link: str,
) -> str:
    return f"""
Стата по загруженным тобой мемам:
📥 Загружено мемов: {len(user_uploaded_memes)}
👁️ Просмотры: {views}
👍 Доля лайков: {like_percent}%

Смотри топ-5 мемов недели в нашем канале: {message_link}
        """


def _en_user_text(
    user_uploaded_memes: list[dict],
    *,
    views: int,
    like_percent: int,
    message_link: str,
) -> str:
    return f"""
Your stats for uploaded memes:
📥 Uploaded memes: {len(user_uploaded_memes)}
👁️ Views: {views}
👍 Like %: {like_percent}%

Check out top-5 uploaded memes of the week in our channel: {message_link}
        """


async def _reward_users_for_weekly_top_uploaded_memes(
    *,
    uploaded_memes: list[dict],
    channel: Channel,
    channel_chat_id: int,
    channel_link: str,
    channel_text_builder,
    user_text_builder,
) -> None:
    logger = get_run_logger()
    logger.info("Received %d uploaded memes", len(uploaded_memes))

    if len(uploaded_memes) < 5:
        await log(f"Not enough memes to reward users: only {len(uploaded_memes)}")
        return

    uploaded_count = len(uploaded_memes)
    user_count = len({m["author_id"] for m in uploaded_memes})
    views = sum(m["nmemes_sent"] for m in uploaded_memes)
    likes = sum(m["nlikes"] for m in uploaded_memes)
    dislikes = sum(m["ndislikes"] for m in uploaded_memes)
    logger.info(
        "Uploaded: %d by %d, views: %d, like%%: %.3f",
        uploaded_count,
        user_count,
        views,
        _like_percent(likes, dislikes) / 100,
    )

    today = datetime.today().date().strftime("%Y-%m-%d")
    top_memes = _top_uploaded_memes(uploaded_memes)

    for i, top_meme in enumerate(top_memes):
        await pay_if_not_paid_with_alert(
            bot,
            top_meme["author_id"],
            REWARD_TRX_TYPES[i],
            external_id=today,
        )

        if top_meme["status"] != MemeStatus.PUBLISHED:
            await update_meme(top_meme["meme_id"], status=MemeStatus.PUBLISHED)

    channel_text = channel_text_builder(
        top_memes,
        uploaded_count=uploaded_count,
        user_count=user_count,
        views=views,
        likes=likes,
        dislikes=dislikes,
    )
    messages = await bot.send_media_group(
        channel_chat_id,
        [_meme_dict_to_input_media(m) for m in top_memes],
        caption=channel_text,
        parse_mode="HTML",
    )

    # log_meme_sent failures must NOT propagate — Prefect would retry the flow
    # and re-publish the album publicly. Missing one diversity-cap row is the
    # smaller harm; the safe block below mirrors the author-notify pattern.
    for i, top_meme in enumerate(top_memes):
        try:
            await log_meme_sent(
                top_meme["meme_id"],
                channel=channel,
                telegram_message_id=messages[i].id,
                caption_text=channel_text if i == 0 else None,
                score_version=REWARD_ALBUM_SCORE_VERSION,
            )
        except Exception as e:
            logger.error(f"Failed to log meme_sent for {top_meme['meme_id']}: {e}")

    message_link = f"{channel_link}/{messages[0].id}"
    author_ids = {m["author_id"] for m in top_memes}
    logger.info("Going to notify %d authors about rewards", len(author_ids))
    for author_id in author_ids:
        user_uploaded_memes = [m for m in uploaded_memes if m["author_id"] == author_id]
        user_likes = sum(m["nlikes"] for m in user_uploaded_memes)
        user_dislikes = sum(m["ndislikes"] for m in user_uploaded_memes)
        user_views = sum(m["nmemes_sent"] for m in user_uploaded_memes)
        user_text = user_text_builder(
            user_uploaded_memes,
            views=user_views,
            like_percent=_like_percent(user_likes, user_dislikes),
            message_link=message_link,
        )
        try:
            await bot.send_message(author_id, user_text)
        except Exception as e:
            logger.error(f"Failed to send message to {author_id}: {e}")

        await asyncio.sleep(2)


@flow(
    name="Reward RU users for weekly top uploaded memes",
    retries=1,
    retry_delay_seconds=60,
    timeout_seconds=300,
    on_failure=[notify_telegram_on_failure],
)
async def reward_ru_users_for_weekly_top_uploaded_memes():
    logger = get_run_logger()
    logger.info("Going to reward users for weekly top uploaded memes")
    await _reward_users_for_weekly_top_uploaded_memes(
        uploaded_memes=await get_all_uploaded_memes_weekly_ru(),
        channel=Channel.TG_CHANNEL_RU,
        channel_chat_id=TELEGRAM_CHANNEL_RU_CHAT_ID,
        channel_link=TELEGRAM_CHANNEL_RU_LINK,
        channel_text_builder=_ru_channel_text,
        user_text_builder=_ru_user_text,
    )


@flow(
    name="Reward EN users for weekly top uploaded memes",
    retries=1,
    retry_delay_seconds=60,
    timeout_seconds=300,
    on_failure=[notify_telegram_on_failure],
)
async def reward_en_users_for_weekly_top_uploaded_memes():
    logger = get_run_logger()
    logger.info("Going to reward users for weekly top uploaded memes")
    await _reward_users_for_weekly_top_uploaded_memes(
        uploaded_memes=await get_all_uploaded_memes_weekly_en(),
        channel=Channel.TG_CHANNEL_EN,
        channel_chat_id=TELEGRAM_CHANNEL_EN_CHAT_ID,
        channel_link=TELEGRAM_CHANNEL_EN_LINK,
        channel_text_builder=_en_channel_text,
        user_text_builder=_en_user_text,
    )
