import random
from html import escape

from prefect import flow, get_run_logger
from telegram.constants import ParseMode

from src.crossposting.constants import Channel
from src.crossposting.service import (
    get_next_meme_for_tgchannelen,
    get_next_meme_for_tgchannelru,
    log_meme_sent,
)
from src.flows.hooks import notify_telegram_on_failure
from src.storage.constants import MemeStatus
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

CTAS = [
    "Начать смотреть мемы",
    "Смотри мемы",
    "Больше мемов",
    "Мемы тут",
    "100к мемов",
    "Анлим мемес",
    "Отправь маме",
    "Перешли папе",
    "Не скучай",
    "Время мемов",
    "Отборные мемы",
    "Нажми сюда",
    "Кликнул быстро",
    "Еще мемы",
    "Листай дальше",
    "Покажи друзьям",
    "Угар гарантирован",
    "Смешно будет",
    "Мемов завезли",
    "Ещё смешнее",
    "Плюс настроение",
    "Смех продлевает жизнь",
    "Бери не стесняйся",
    "Запас мемов",
    "Легендарные мемы",
    "Кайфуй от мемов",
    "Залетай сюда",
    "Врывайся в мемы",
    "Лютые мемы",
    "Загружай мозг",
    "Гигачад мемес",
    "Жиза в мемах",
    "Не пропусти",
    "Кринжанёшь",
    "Рассмей кота",
    "Зови друзей",
    "Гига смех",
    "Кек момент",
    "Залипай сюда",
    "Фулл рофл",
    "Нереальные мемы",
    "Кринж или рофл?",
    "Легенда мемов",
    "Батя заценит",
    "Шутки за 300",
    "Тест на смех",
    "Мемный поток",
    "Пошло поехало",
    "Слабак не нажмёт",
    "Ты не готов",
    "Осилишь все мемы?",
    "Держись, будет угар",
    "Не смейся, чел",
    "Это слишком смешно",
    "Ты точно выдержишь?",
    "Потрачено",
    "Фулл разнос",
    "Если засмеёшься — лайк",
    "Пробуй не зарофлить",
    "Жиза или нет?",
    "Чел, ты это видел?",
    "Это бан",
    "Кринжанёшь жёстко",
    "Мамкин мемолог",
    "Гарантия ор выше гор",
    "Смешно? Покажи другу",
    "Улетишь в космос",
    "Батя будет в шоке",
    "Ты за это подпишешься",
    "Здесь решается судьба",
    "Мемы не для слабых",
    "Рискни открыть",
    "Смело нажимай",
    "Готов к жести?",
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


def _get_en_caption_for_crossposting_meme(meme: MemeData, channel: Channel) -> str:
    ref_link = "https://t.me/ffmemesbot?start=sc_{}_{}".format(meme.id, channel.value)

    emoji = get_random_emoji()
    referral_html = f"""{emoji} <i><a href="{ref_link}">Fast Food Memes</a></i>"""
    caption = escape(meme.caption, quote=False) if meme.caption else ""
    text = caption + "\n\n" + referral_html
    return text


@flow(
    retries=2,
    retry_delay_seconds=30,
    timeout_seconds=300,
    on_failure=[notify_telegram_on_failure],
)
async def post_meme_to_tgchannelen():
    logger = get_run_logger()

    meme_data = await get_next_meme_for_tgchannelen()
    next_meme = MemeData(**meme_data)
    logger.info(f"Next meme for TG Channel EN: {next_meme.id}")

    next_meme.caption = _get_en_caption_for_crossposting_meme(next_meme, Channel.TG_CHANNEL_EN)
    msg = await send_new_message_with_meme(
        bot, TELEGRAM_CHANNEL_EN_CHAT_ID, next_meme, reply_markup=None
    )

    await log_meme_sent(next_meme.id, Channel.TG_CHANNEL_EN)
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

    meme_data = await get_next_meme_for_tgchannelru()
    next_meme = MemeData(**meme_data)
    logger.info(f"Next meme for TG Channel RU: {next_meme.id}")

    next_meme.caption = _get_ru_caption_for_crossposting_meme(next_meme, Channel.TG_CHANNEL_RU)

    msg = await send_new_message_with_meme(
        bot, TELEGRAM_CHANNEL_RU_CHAT_ID, next_meme, reply_markup=None
    )

    await log_meme_sent(next_meme.id, Channel.TG_CHANNEL_RU)
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
