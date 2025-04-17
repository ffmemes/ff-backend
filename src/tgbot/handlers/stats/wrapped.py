import asyncio
import datetime

from openai import AsyncOpenAI
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from src.config import settings
from src.redis import get_user_wrapped, set_user_wrapped
from src.stats.meme_source import calculate_meme_source_stats
from src.stats.service import (
    get_most_liked_meme_source_urls,
    get_ocr_text_of_liked_memes_for_llm,
    get_shared_memes,
    get_user_stats,
)
from src.stats.user import calculate_inviter_stats, calculate_user_stats
from src.stats.user_meme_source import calculate_user_meme_source_stats
from src.storage.schemas import MemeData
from src.tgbot.constants import TELEGRAM_CHANNEL_RU_CHAT_ID, TELEGRAM_CHANNEL_RU_LINK
from src.tgbot.senders.meme import send_new_message_with_meme
from src.tgbot.service import (
    create_or_update_user,
    get_meme_by_id,
    get_user_by_id,
    save_tg_user,
)
from src.tgbot.utils import check_if_user_chat_member


async def call_chatgpt(prompt: str) -> str:
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    response = await client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}],
            }
        ],
        max_tokens=500,
    )
    return response.choices[0].message.content


async def handle_wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    await create_or_update_user(id=user_id)
    await save_tg_user(
        id=user_id,
        username=update.effective_user.username,
        first_name=update.effective_user.first_name,
        last_name=update.effective_user.last_name,
        is_premium=update.effective_user.is_premium,
        language_code=update.effective_user.language_code,
    )

    if not await check_if_user_chat_member(
        context.bot,
        user_id,
        TELEGRAM_CHANNEL_RU_CHAT_ID,
    ):
        return await update.message.reply_text(
            f"""
Статистика доступна только подписчикам нашего канала 😉

Подпишись:
{TELEGRAM_CHANNEL_RU_LINK}
            """
        )

    user_wrapped = await get_user_wrapped(user_id)
    if not user_wrapped:
        user_wrapped = await generate_user_wrapped(user_id, update)
        if user_wrapped is None:
            return
        print(f"Generated wrapped for user_id={user_id}: {user_wrapped}")
        await set_user_wrapped(user_id, user_wrapped)

    elif user_wrapped.get("lock"):
        return  # user already clicked

    return await handle_wrapped_button(update, context)


async def handle_wrapped_button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    user_wrapped = await get_user_wrapped(update.effective_user.id)

    if update.callback_query:
        await update.callback_query.answer()
        key = int(update.callback_query.data.replace("wrapped_", ""))
    else:
        key = 0

    if key == 0:
        await update.effective_chat.send_message(
            text=user_wrapped["bot_usage_report"],
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Дальше", callback_data="wrapped_1")]]
            ),
        )
    if key == 1:
        await update.effective_chat.send_message(
            text=user_wrapped["recommended_meme_sources_report"],
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Дальше", callback_data="wrapped_2")]]
            ),
        )
    if key == 2:
        meme_data = user_wrapped["most_shared_meme_report"]
        if meme_data is not None:
            meme = MemeData(**meme_data)
            await send_new_message_with_meme(
                context.bot,
                update.effective_user.id,
                meme,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Дальше", callback_data="wrapped_3")]]
                ),
            )
        else:
            key = 3

    if key == 3 and user_wrapped["humor_sense_report"]:
        await update.effective_chat.send_message(
            text=user_wrapped["humor_sense_report"],
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Финалочка", callback_data="wrapped_4")]]
            ),
        )

    if key == 4:
        await update.effective_chat.send_message(
            text="""
❤️ Спасибо большое за то, что пользуешься ботом. Мы работаем над ним каждый день, чтобы скрасить ваши будни нашими картинками.

Продолжай смотреть мемы и пересылать их друзьям. С профессиональным праздником всех нас!

@ffmemesbot

/start
            """  # noqa: E501
        )

    print("?????? key=", key)


async def generate_user_wrapped(user_id: int, update: Update):
    await set_user_wrapped(user_id, {"lock": True})

    msg = await update.message.reply_text("⏳ Анализирую твои лайки...")

    try:
        await asyncio.gather(
            calculate_user_stats(),
            calculate_inviter_stats(),
            calculate_meme_source_stats(),
            calculate_user_meme_source_stats(),
        )
    except Exception as e:
        print(f"Error in recalculating stats: {e}")
        pass

    bot_usage_report = await get_bot_usage_report(user_id)
    recommended_meme_sources_report = await get_meme_sources_report(user_id)

    if bot_usage_report is None or recommended_meme_sources_report is None:
        await msg.edit_text(
            """
Маловато ты пользовался ботом, чтобы я мог показать тебе что-нибудь интересненькое.

А ну-ка смотреть мемусики ➡️ жми /start
            """
        )
        return

    await msg.edit_text("⏳")
    most_shared_meme_report = await get_most_shared_meme_report(user_id)

    humor_sense_report = await get_humor_report(user_id)

    await asyncio.sleep(1)
    await msg.edit_text("⬇️ ГОТОВО ⬇️")
    await asyncio.sleep(2)

    return {
        "bot_usage_report": bot_usage_report,
        "recommended_meme_sources_report": recommended_meme_sources_report,
        "most_shared_meme_report": most_shared_meme_report,
        "humor_sense_report": humor_sense_report,
    }


async def get_bot_usage_report(user_id: int):
    user = await get_user_by_id(user_id)

    user_stats = await get_user_stats(user_id)
    if user_stats is None:
        return None

    days_with_us = (datetime.datetime.utcnow() - user["created_at"]).days + 1
    user_opened_bot_times = user_stats.get("nsessions", 0)

    we_sent_memes = user_stats.get("nmemes_sent", 0)
    user_gave_likes = user_stats.get("nlikes", 0)
    user_spent_sec = user_stats.get("time_spent_sec", 0)
    user_invited_users = user_stats.get("invited_users", [])

    if user_gave_likes < 10:
        return None

    REPORT = f"""
Ты присоединился к боту {days_with_us} дней назад.

За это время ты
👋 открыл бота {user_opened_bot_times} раз
👍 поставил {user_gave_likes} лайков
🤝 получил {we_sent_memes} мемов
    """.strip()

    if user_spent_sec > 0:
        if user_spent_sec < 60:
            REPORT += f"\n🕒 провел в боте {user_spent_sec} секунд\n"
        elif user_spent_sec < 3600:
            minutes = user_spent_sec // 60
            seconds = user_spent_sec % 60
            REPORT += f"\n🕗 провел в боте {minutes} минут {seconds} секунд\n"
        else:
            hours = user_spent_sec // 3600
            REPORT += f"\n🕑 провел в боте чуть больше {hours} часов 😳\n"

    if user_invited_users > 1:
        REPORT += f"""
Ты отправлял мемы из бота друзьям и тем самым пригласил {user_invited_users} человек.
        """
    elif user_invited_users == 1:
        REPORT += """
Ты отправлял мемы из бота друзьям, один из них даже перешел в бота!
        """

    return REPORT


async def get_meme_sources_report(user_id, limit=3):
    meme_source_urls = await get_most_liked_meme_source_urls(user_id, limit)
    if not meme_source_urls:
        return None

    sources_list = "\n".join(f"▪️ {source['url']}" for source in meme_source_urls)

    REPORT = f"""
Проанализировав твое чувство юмора, я могу с уверенностью сказать: ты точно заценишь вот эти паблосы:

{sources_list}
    """  # noqa: E501

    return REPORT


async def get_most_shared_meme_report(user_id, limit=10):
    shared_memes = await get_shared_memes(user_id, limit=1)
    if not shared_memes:
        return None

    shared_meme_id = shared_memes[0]["meme_id"]
    meme_data = await get_meme_by_id(shared_meme_id)
    if meme_data:
        caption = """Твои друзья больше всего орнули с этого мема 🤦‍♂️"""
        if meme_data["caption"] is not None:
            caption += "\n\n" + meme_data["caption"]
        return {
            "id": meme_data["id"],
            "type": meme_data["type"],
            "telegram_file_id": meme_data["telegram_file_id"],
            "caption": caption,
        }


async def get_humor_report(user_id):
    ocrs = await get_ocr_text_of_liked_memes_for_llm(user_id)
    if not ocrs:
        return None

    texts = "\n".join(f"{ocr['ocr_text']}" for ocr in ocrs)
    if len(texts) < 100:
        return None

    PROMPT = f"""

Цель: Создать уникальный и забавный профиль моего чувства юмора, используя анализ мемов.

Задача в двух словах: Изучи тексты моих любимых мемов и скажи, что они говорят о моем чувстве юмора. Сделай это через призму забавы и неформальности.

Что тебе нужно знать:
Некоторые тексты могут быть нечеткими из-за ошибок распознавания или случайных элементов интерфейса - игнорируй трудные для понимания.
Важно: Сосредоточься на текстах, которые ясно передают юмор.
Список текстов из 20 мемов:

{texts}

Ожидаемый формат ответа:
Только 3 пункта. Ни больше, ни меньше.
Упоминай мемы напрямую, но избегай повторения и скучных обобщений. Нет двойных скобок, только суть.

Примеры, которые ты можешь использовать как вдохновение (не включать в ответ):
Твоё чувство юмора как вирус в космосе – редкое и загадочное, идёт вразрез с ожиданиями и заставляет задуматься, а затем внезапно смеяться над абсурдностью повседневности.
Ты как тот, кто с удовольствием наблюдает, как гигантская моль покидает дом, в то время как остальные борются с экселевскими таблицами, и считаешь душ лучшим местом для вечной жизни.
В общем, твой юмор – это шавуха превращающаяся в струю поноса, удивительный и слегка сбивающий с толку.

Вот и всё! Используй эти указания, чтобы дать мне три пункта, раскрывающих суть моего чувства юмора через анализ предоставленных мемов. Каждый пункт должен давать полезный инсайт про мое чувство юмора. Каждый пункт должен звучать так, как будто его говорит тебе друг - неформально, в простой форме. Каждый пункт должен быть 1-2 предложения, короткий. За идеальный ответ я смогу дать тебе 500$ чаевых.
    """  # noqa: E501

    result = await call_chatgpt(PROMPT)

    REPORT = f"""
👀 Я посмотрел на твои лайки и немножко понял твое чувство юмора:

{result}
    """

    return REPORT
