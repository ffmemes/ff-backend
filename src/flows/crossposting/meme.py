import random
import re
from html import escape

from prefect import flow, get_run_logger
from telegram.constants import ParseMode

from src.crossposting.constants import Channel
from src.crossposting.service import (
    get_next_meme_for_tgchannelen,
    get_next_meme_for_tgchannelru,
    get_next_share_max_meme_for_tgchannelen,
    get_next_share_max_meme_for_tgchannelru,
    log_meme_sent,
    log_ranker_decision,
)
from src.crossposting.vk import post_photo_to_group
from src.flows.hooks import notify_telegram_on_failure
from src.storage.constants import MemeStatus, MemeType
from src.storage.schemas import MemeData
from src.storage.service import update_meme
from src.tgbot.bot import bot
from src.tgbot.constants import (
    TELEGRAM_CHANNEL_EN_CHAT_ID,
    TELEGRAM_CHANNEL_EN_LINK,
    TELEGRAM_CHANNEL_RU_CHAT_ID,
    TELEGRAM_CHANNEL_RU_LINK,
)
from src.tgbot.handlers.treasury.constants import PAYOUTS, TrxType
from src.tgbot.handlers.treasury.payments import pay_if_not_paid
from src.tgbot.handlers.upload.service import get_meme_uploader_user_id
from src.tgbot.senders.meme import send_new_message_with_meme
from src.tgbot.senders.utils import get_random_emoji

# when we tried to explain meme in the post caption
# we received lots of negative feedback from users
# and number of post shares decreased significantly

# CTAs ranked by forward rate from 11K post analysis (2026-04-13).
# Top tier (>20 fwd/1k): challenge/dare CTAs that provoke action.
# Removed: "Фулл разнос" (11.2), "Держись, будет угар" (12.4), "Рассмей кота" (13.0),
# "Легендарные мемы" (13.4), "Готов к жести?" (13.5), "Не пропусти" (14.3),
# "Больше мемов" (14.5), "Шутки за 300" (14.8), "Листай дальше" (15.1),
# "Отправь маме" (15.3) — all below 16 fwd/1k.
CTAS = [
    # Top tier (>20 fwd/1k) — 3x weight via repetition
    "Улетишь в космос",
    "Улетишь в космос",
    "Улетишь в космос",
    "Если засмеёшься — лайк",
    "Если засмеёшься — лайк",
    "Если засмеёшься — лайк",
    "Кликнул быстро",
    "Кликнул быстро",
    "Кликнул быстро",
    "Смело нажимай",
    "Смело нажимай",
    "Смело нажимай",
    "Осилишь все мемы?",
    "Осилишь все мемы?",
    "Осилишь все мемы?",
    "Запас мемов",
    "Запас мемов",
    "Запас мемов",
    "Тест на смех",
    "Тест на смех",
    "Тест на смех",
    "Не смейся, чел",
    "Не смейся, чел",
    "Не смейся, чел",
    "Гарантия ор выше гор",
    "Гарантия ор выше гор",
    "Гарантия ор выше гор",
    "Жиза или нет?",
    "Жиза или нет?",
    "Жиза или нет?",
    "Смешно? Покажи другу",
    "Смешно? Покажи другу",
    "Смешно? Покажи другу",
    # Mid tier (16-20 fwd/1k) — 1x weight
    "Мемы тут",
    "100к мемов",
    "Анлим мемес",
    "Перешли папе",
    "Не скучай",
    "Время мемов",
    "Отборные мемы",
    "Нажми сюда",
    "Покажи друзьям",
    "Угар гарантирован",
    "Смешно будет",
    "Мемов завезли",
    "Ещё смешнее",
    "Кайфуй от мемов",
    "Залетай сюда",
    "Врывайся в мемы",
    "Лютые мемы",
    "Гигачад мемес",
    "Жиза в мемах",
    "Кринжанёшь",
    "Зови друзей",
    "Кек момент",
    "Залипай сюда",
    "Нереальные мемы",
    "Кринж или рофл?",
    "Батя заценит",
    "Мемный поток",
    "Пошло поехало",
    "Слабак не нажмёт",
    "Ты не готов",
    "Это слишком смешно",
    "Ты точно выдержишь?",
    "Потрачено",
    "Пробуй не зарофлить",
    "Чел, ты это видел?",
    "Это бан",
    "Кринжанёшь жёстко",
    "Мамкин мемолог",
    "Батя будет в шоке",
    "Ты за это подпишешься",
    "Здесь решается судьба",
    "Мемы не для слабых",
    "Рискни открыть",
    "Начать смотреть мемы",
    "Смотри мемы",
    "Еще мемы",
    "Плюс настроение",
    "Смех продлевает жизнь",
    "Бери не стесняйся",
    "Загружай мозг",
    "Фулл рофл",
    "Легенда мемов",
    "Гига смех",
]


def _get_ru_caption_for_crossposting_meme(meme: MemeData, channel: Channel) -> str:
    cta = random.choice(CTAS)
    ref_link = "https://t.me/ffmemesbot?start=sc_{}_{}".format(meme.id, channel.value)

    # emoji = get_random_emoji()
    # referral_html = f"""{emoji} <i><a href="{ref_link}">Fast Food Memes</a></i>"""
    # caption = escape(meme.caption, quote=False) if meme.caption else ""
    # text = caption + "\n\n" + referral_html

    text = cta + ": " + f"""<a href="{ref_link}">@ffmemesbot</a>"""

    return text


def _clean_caption(caption: str) -> str:
    """Strip source attribution lines from Reddit-sourced meme captions."""
    lines = caption.splitlines()
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # Skip Reddit URLs
        if re.search(r"https?://(www\.)?(reddit\.com|redd\.it)", stripped):
            continue
        # Skip Telegram @handles
        if re.match(r"^@\S+$", stripped):
            continue
        # Skip subreddit-like tokens (single word, only alphanumeric + underscores)
        if re.match(r"^[A-Za-z0-9_]{1,30}$", stripped):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def _get_vk_caption_for_crossposting_meme(meme: MemeData) -> str:
    """VK doesn't render HTML; uses plain-text caption with auto-linkified URL."""
    cta = random.choice(CTAS)
    ref_link = "https://t.me/ffmemesbot?start=sc_{}_{}".format(meme.id, Channel.VK_GROUP_RU.value)
    return f"{cta}: {ref_link}"


def _get_en_caption_for_crossposting_meme(meme: MemeData, channel: Channel) -> str:
    ref_link = "https://t.me/ffmemesbot?start=sc_{}_{}".format(meme.id, channel.value)

    emoji = get_random_emoji()
    referral_html = f"""{emoji} <i><a href="{ref_link}">Fast Food Memes</a></i>"""
    raw_caption = meme.caption or ""
    caption = escape(_clean_caption(raw_caption), quote=False)
    text = (caption + "\n\n" + referral_html) if caption else referral_html
    return text


@flow(
    retries=2,
    retry_delay_seconds=30,
    timeout_seconds=300,
    on_failure=[notify_telegram_on_failure],
)
async def post_meme_to_tgchannelen():
    logger = get_run_logger()

    meme_data, decision = await get_next_meme_for_tgchannelen()
    if meme_data is None:
        logger.warning("No qualifying meme for TG Channel EN, skipping slot")
        return
    next_meme = MemeData(**meme_data)
    logger.info(f"Next meme for TG Channel EN: {next_meme.id}")

    # Persist the ranker decision for retro analysis. Failure must NOT propagate
    # — Prefect retry would republish the meme.
    if decision:
        try:
            await log_ranker_decision(**decision)
        except Exception as e:
            logger.error(f"log_ranker_decision failed for {next_meme.id}: {e}")

    caption_text = _get_en_caption_for_crossposting_meme(next_meme, Channel.TG_CHANNEL_EN)
    next_meme.caption = caption_text
    msg = await send_new_message_with_meme(
        bot, TELEGRAM_CHANNEL_EN_CHAT_ID, next_meme, reply_markup=None
    )

    await log_meme_sent(
        next_meme.id,
        Channel.TG_CHANNEL_EN,
        telegram_message_id=msg.message_id,
        caption_text=caption_text,
        score_version=2,
    )
    await update_meme(next_meme.id, status=MemeStatus.PUBLISHED)

    uploader_user_id = await get_meme_uploader_user_id(next_meme.id)
    if uploader_user_id:
        balance = await pay_if_not_paid(uploader_user_id, TrxType.MEME_PUBLISHED, str(next_meme.id))
        if balance:
            link = TELEGRAM_CHANNEL_EN_LINK + "/" + str(msg.message_id)
            await bot.send_message(
                uploader_user_id,
                f"""
/b: +<b>{PAYOUTS[TrxType.MEME_PUBLISHED]}</b> 🍔 because we <a href="{link}">posted your meme in our channel</a>.
                """,  # noqa
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )


@flow(
    retries=2,
    retry_delay_seconds=30,
    timeout_seconds=300,
    on_failure=[notify_telegram_on_failure],
)
async def post_meme_to_tgchannelru():
    logger = get_run_logger()

    meme_data, decision = await get_next_meme_for_tgchannelru()
    if meme_data is None:
        logger.warning("No qualifying meme for TG Channel RU, skipping slot")
        return
    next_meme = MemeData(**meme_data)
    logger.info(f"Next meme for TG Channel RU: {next_meme.id}")

    # Persist the ranker decision for retro analysis. Failure must NOT propagate
    # — Prefect retry would republish the meme.
    if decision:
        try:
            await log_ranker_decision(**decision)
        except Exception as e:
            logger.error(f"log_ranker_decision failed for {next_meme.id}: {e}")

    caption_text = _get_ru_caption_for_crossposting_meme(next_meme, Channel.TG_CHANNEL_RU)
    next_meme.caption = caption_text

    msg = await send_new_message_with_meme(
        bot, TELEGRAM_CHANNEL_RU_CHAT_ID, next_meme, reply_markup=None
    )

    await log_meme_sent(
        next_meme.id,
        Channel.TG_CHANNEL_RU,
        telegram_message_id=msg.message_id,
        caption_text=caption_text,
        score_version=2,
    )
    await update_meme(next_meme.id, status=MemeStatus.PUBLISHED)

    if next_meme.type == MemeType.IMAGE:
        try:
            tg_file = await bot.get_file(next_meme.telegram_file_id)
            file_bytes = bytes(await tg_file.download_as_bytearray())
            vk_caption = _get_vk_caption_for_crossposting_meme(next_meme)
            vk_result = await post_photo_to_group(file_bytes, vk_caption)
            await log_meme_sent(
                next_meme.id,
                Channel.VK_GROUP_RU,
                telegram_message_id=vk_result.get("post_id"),
                caption_text=vk_caption,
                score_version=2,
            )
            logger.info(f"VK posted meme {next_meme.id} as post_id={vk_result.get('post_id')}")
        except Exception as e:
            logger.error(f"VK crosspost failed for meme {next_meme.id}: {e}")

    uploader_user_id = await get_meme_uploader_user_id(next_meme.id)
    if uploader_user_id:
        balance = await pay_if_not_paid(uploader_user_id, TrxType.MEME_PUBLISHED, str(next_meme.id))
        if balance:
            link = TELEGRAM_CHANNEL_RU_LINK + "/" + str(msg.message_id)
            await bot.send_message(
                uploader_user_id,
                f"""
/b: +<b>{PAYOUTS[TrxType.MEME_PUBLISHED]}</b> 🍔 за то, что мы <a href="{link}">запостили твой мем к себе в канал</a>.
                """,  # noqa
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )


@flow(
    name="Post Share Max Meme to TG Channel EN",
    retries=0,
    timeout_seconds=300,
    on_failure=[notify_telegram_on_failure],
)
async def post_share_max_meme_to_tgchannelen():
    """One-shot experimental post using score_version=3 share-max ranking."""
    logger = get_run_logger()

    meme_data, decision = await get_next_share_max_meme_for_tgchannelen(
        respect_recent_source_cap=False
    )
    if meme_data is None:
        logger.warning("No qualifying share-max meme for TG Channel EN, skipping slot")
        return
    next_meme = MemeData(**meme_data)
    logger.info(f"Next share-max meme for TG Channel EN: {next_meme.id}")

    if decision:
        try:
            await log_ranker_decision(**decision)
        except Exception as e:
            logger.error(f"log_ranker_decision failed for share-max {next_meme.id}: {e}")

    caption_text = _get_en_caption_for_crossposting_meme(next_meme, Channel.TG_CHANNEL_EN)
    next_meme.caption = caption_text
    msg = await send_new_message_with_meme(
        bot, TELEGRAM_CHANNEL_EN_CHAT_ID, next_meme, reply_markup=None
    )

    await log_meme_sent(
        next_meme.id,
        Channel.TG_CHANNEL_EN,
        telegram_message_id=msg.message_id,
        caption_text=caption_text,
        score_version=3,
    )
    await update_meme(next_meme.id, status=MemeStatus.PUBLISHED)

    uploader_user_id = await get_meme_uploader_user_id(next_meme.id)
    if uploader_user_id:
        balance = await pay_if_not_paid(uploader_user_id, TrxType.MEME_PUBLISHED, str(next_meme.id))
        if balance:
            link = TELEGRAM_CHANNEL_EN_LINK + "/" + str(msg.message_id)
            await bot.send_message(
                uploader_user_id,
                f"""
/b: +<b>{PAYOUTS[TrxType.MEME_PUBLISHED]}</b> 🍔 because we <a href="{link}">posted your meme in our channel</a>.
                """,  # noqa
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )


@flow(
    name="Post Share Max Meme to TG Channel RU",
    retries=0,
    timeout_seconds=300,
    on_failure=[notify_telegram_on_failure],
)
async def post_share_max_meme_to_tgchannelru():
    """One-shot experimental post using score_version=3 share-max ranking.

    Unlike the scheduled RU flow, this does not crosspost to VK; the experiment
    isolates Telegram channel forwards.
    """
    logger = get_run_logger()

    meme_data, decision = await get_next_share_max_meme_for_tgchannelru()
    if meme_data is None:
        logger.warning("No qualifying share-max meme for TG Channel RU, skipping slot")
        return
    next_meme = MemeData(**meme_data)
    logger.info(f"Next share-max meme for TG Channel RU: {next_meme.id}")

    if decision:
        try:
            await log_ranker_decision(**decision)
        except Exception as e:
            logger.error(f"log_ranker_decision failed for share-max {next_meme.id}: {e}")

    caption_text = _get_ru_caption_for_crossposting_meme(next_meme, Channel.TG_CHANNEL_RU)
    next_meme.caption = caption_text

    msg = await send_new_message_with_meme(
        bot, TELEGRAM_CHANNEL_RU_CHAT_ID, next_meme, reply_markup=None
    )

    await log_meme_sent(
        next_meme.id,
        Channel.TG_CHANNEL_RU,
        telegram_message_id=msg.message_id,
        caption_text=caption_text,
        score_version=3,
    )
    await update_meme(next_meme.id, status=MemeStatus.PUBLISHED)

    uploader_user_id = await get_meme_uploader_user_id(next_meme.id)
    if uploader_user_id:
        balance = await pay_if_not_paid(uploader_user_id, TrxType.MEME_PUBLISHED, str(next_meme.id))
        if balance:
            link = TELEGRAM_CHANNEL_RU_LINK + "/" + str(msg.message_id)
            await bot.send_message(
                uploader_user_id,
                f"""
/b: +<b>{PAYOUTS[TrxType.MEME_PUBLISHED]}</b> 🍔 за то, что мы <a href="{link}">запостили твой мем к себе в канал</a>.
                """,  # noqa
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
