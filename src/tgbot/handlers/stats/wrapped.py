import datetime
import json
import logging
import random

from openai import AsyncOpenAI
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from src.config import settings
from src.redis import get_user_wrapped, set_user_wrapped
from src.stats.service import (
    get_meme_descriptions_for_wrapped,
    get_most_liked_meme_source_urls,
    get_user_stats,
)
from src.storage.schemas import MemeData
from src.tgbot.constants import (
    TELEGRAM_CHANNEL_RU_CHAT_ID,
    TELEGRAM_CHANNEL_RU_LINK,
)
from src.tgbot.senders.meme import send_new_message_with_meme
from src.tgbot.service import (
    create_or_update_user,
    get_meme_by_id,
    get_user_by_id,
    save_tg_user,
)
from src.tgbot.utils import check_if_user_chat_member

logger = logging.getLogger(__name__)

WRAPPED_MIN_REACTIONS = 30
WRAPPED_MIN_DESCRIPTIONS = 5


async def call_chatgpt(prompt: str) -> str:
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    response = await client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "user", "content": [{"type": "text", "text": prompt}]},
        ],
        max_tokens=500,
    )
    return response.choices[0].message.content


async def call_chatgpt_json(prompt: str) -> dict | None:
    """Call ChatGPT and parse JSON response."""
    try:
        raw = await call_chatgpt(prompt)
        content = raw.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        if content.startswith("json"):
            content = content[4:].strip()
        return json.loads(content)
    except Exception as e:
        logger.warning("Failed to parse LLM JSON: %s", e)
        return None


def get_user_interface_language(user) -> str:
    lang = user.get("language_code") if user else None
    return lang if lang else "ru"


async def is_wrapped_auto_trigger_active(user_id: int) -> bool:
    now = datetime.datetime.utcnow()
    if now < datetime.datetime(2026, 4, 1):
        user = await get_user_by_id(user_id)
        return user and user.get("type") in ("moderator", "admin")
    if now <= datetime.datetime(2026, 4, 7):
        return True
    return False


# ──────────────────────────────────────────────────────────
# MAIN HANDLER
# ──────────────────────────────────────────────────────────

async def handle_wrapped(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
) -> None:
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

    # Channel subscription gate
    if not await check_if_user_chat_member(
        context.bot, user_id, TELEGRAM_CHANNEL_RU_CHAT_ID,
    ):
        return await update.message.reply_text(
            f"Статистика доступна только подписчикам нашего канала 😉\n\n"
            f"Подпишись:\n{TELEGRAM_CHANNEL_RU_LINK}"
        )

    # If already cached — go straight to slides
    user_wrapped = await get_user_wrapped(user_id)
    if user_wrapped and not user_wrapped.get("lock"):
        return await handle_wrapped_button(update, context)
    if user_wrapped and user_wrapped.get("lock"):
        return

    # ── FIX #1: Instant welcome message with fun buttons ──
    await update.effective_chat.send_message(
        text=(
            "🎁 Мы подготовили глубокий анализ твоего чувства юмора.\n\n"
            "Хочешь посмотреть?"
        ),
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("ДА", callback_data="wrapped_go"),
                InlineKeyboardButton(
                    "ПОСМОТРЕТЬ", callback_data="wrapped_go",
                ),
            ]
        ]),
    )


async def handle_wrapped_go(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """User pressed ДА / ПОСМОТРЕТЬ — start generating."""
    if update.callback_query:
        await update.callback_query.answer()

    user_id = update.effective_user.id

    # Already cached?
    user_wrapped = await get_user_wrapped(user_id)
    if user_wrapped and not user_wrapped.get("lock"):
        return await handle_wrapped_button(update, context)
    if user_wrapped and user_wrapped.get("lock"):
        return

    # Check minimums
    user_stats_data = await get_user_stats(user_id)
    if not user_stats_data:
        return await update.effective_chat.send_message(
            "Маловато ты пользовался ботом 😅\n"
            "Посмотри побольше мемов и возвращайся! /start"
        )

    nmemes_sent = user_stats_data.get("nmemes_sent", 0)
    if nmemes_sent < WRAPPED_MIN_REACTIONS:
        remaining = WRAPPED_MIN_REACTIONS - nmemes_sent
        return await update.effective_chat.send_message(
            f"Посмотри ещё {remaining} мемов, чтобы получить Wrapped 🎁\n"
            f"Жми /start и листай!"
        )

    descriptions = await get_meme_descriptions_for_wrapped(
        user_id, limit=30,
    )
    if len(descriptions) < WRAPPED_MIN_DESCRIPTIONS:
        return await update.effective_chat.send_message(
            "Мы ещё анализируем твои мемы... 🔬\n"
            "Попробуй через пару часов! А пока — /start"
        )

    user = await get_user_by_id(user_id)
    is_ru = get_user_interface_language(user) == "ru"

    # ── FIX #3: Stats slide with "начнём с цифр" intro ──
    bot_usage_report = await get_bot_usage_report(user_id, is_ru)
    if bot_usage_report is None:
        return await update.effective_chat.send_message(
            "Маловато данных 😅 Жми /start"
        )

    # Send stats slide right away
    await update.effective_chat.send_message(
        text=bot_usage_report,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("Дальше →", callback_data="wrapped_1")]]
        ),
    )

    # Generate LLM content while user reads stats
    user_wrapped = await generate_user_wrapped(
        user_id, descriptions, is_ru, bot_usage_report,
    )
    if user_wrapped:
        await set_user_wrapped(user_id, user_wrapped)


# ──────────────────────────────────────────────────────────
# SLIDE NAVIGATION
# ──────────────────────────────────────────────────────────

async def handle_wrapped_button(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
) -> None:
    user_wrapped = await get_user_wrapped(update.effective_user.id)
    if not user_wrapped:
        return

    if user_wrapped.get("lock"):
        if update.callback_query:
            await update.callback_query.answer(
                "⏳ Ещё генерирую... подожди пару секунд",
                show_alert=False,
            )
        return

    if update.callback_query:
        await update.callback_query.answer()
        key = int(update.callback_query.data.replace("wrapped_", ""))
    else:
        key = 0

    # Slide 0: Stats (only when re-entering from cache)
    if key == 0:
        await update.effective_chat.send_message(
            text=user_wrapped["bot_usage_report"],
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(
                    "Дальше →", callback_data="wrapped_1",
                )]]
            ),
        )

    # ── FIX #7: Slide 1 — "Этот мем олицетворяет тебя" (with image) ──
    if key == 1:
        your_meme = user_wrapped.get("your_meme_report")
        if your_meme and your_meme.get("meme_id"):
            meme_data = await get_meme_by_id(your_meme["meme_id"])
            if meme_data:
                meme = MemeData(**meme_data)
                caption = (
                    "🎯 Этот мем олицетворяет тебя:\n\n"
                    f"<i>{your_meme.get('reason', '')}</i>"
                )
                await send_new_message_with_meme(
                    context.bot,
                    update.effective_user.id,
                    meme,
                    caption=caption,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton(
                            "Дальше →", callback_data="wrapped_2",
                        )]]
                    ),
                )
            else:
                key = 2
        else:
            # Fallback: pick a random liked meme
            fallback = user_wrapped.get("random_liked_meme")
            if fallback:
                meme_data = await get_meme_by_id(fallback["meme_id"])
                if meme_data:
                    meme = MemeData(**meme_data)
                    await send_new_message_with_meme(
                        context.bot,
                        update.effective_user.id,
                        meme,
                        caption="🎲 А вот мем, который тебе зашёл:",
                        reply_markup=InlineKeyboardMarkup(
                            [[InlineKeyboardButton(
                                "Дальше →", callback_data="wrapped_2",
                            )]]
                        ),
                    )
                else:
                    key = 2
            else:
                key = 2

    # Slide 2: Humor DNA
    if key == 2:
        humor_report = user_wrapped.get("humor_dna_report", "")
        if humor_report:
            await update.effective_chat.send_message(
                text=humor_report,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(
                        "Дальше →", callback_data="wrapped_3",
                    )]]
                ),
            )
        else:
            key = 3

    # ── FIX #8: Slide 3 — Top 3 мем-паблики ──
    if key == 3:
        sources = user_wrapped.get("meme_sources_report", "")
        if sources:
            await update.effective_chat.send_message(
                text=sources,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(
                        "Финалочка →", callback_data="wrapped_4",
                    )]]
                ),
            )
        else:
            key = 4

    # Slide 4: Prediction + finale
    if key == 4:
        prediction = user_wrapped.get("prediction", "")
        await update.effective_chat.send_message(
            text=(
                "🔮 <b>Предсказание на лето 2026:</b>\n\n"
                f"<i>{prediction}</i>\n\n"
                "❤️ Спасибо за то, что пользуешься ботом.\n"
                "Продолжай смотреть мемы и пересылай их друзьям!\n\n"
                "🍔 @ffmemesbot\n\n"
                "/start"
            ),
            parse_mode="HTML",
        )


async def handle_wrapped_clear(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Admin command to clear Wrapped cache for testing."""
    user_id = update.effective_user.id
    user = await get_user_by_id(user_id)
    if not user or user.get("type") not in ("moderator", "admin"):
        return

    from src.redis import redis_client
    await redis_client.delete(f"wrapped:{user_id}")
    await update.message.reply_text(
        "Wrapped cache cleared ✓ Try /wrapped again."
    )


# ──────────────────────────────────────────────────────────
# GENERATION
# ──────────────────────────────────────────────────────────

async def generate_user_wrapped(
    user_id: int,
    descriptions: list,
    is_ru: bool = True,
    bot_usage_report: str = "",
):
    """Generate all LLM content. Stats slide already sent."""
    await set_user_wrapped(user_id, {"lock": True}, ttl=300)

    try:
        your_meme_report = await get_your_meme_report(
            descriptions, is_ru,
        )
        humor_dna_report = await get_humor_dna_report(
            descriptions, is_ru,
        )
        prediction = await get_prediction(descriptions, is_ru)

        # ── FIX #8: Top 3 meme sources ──
        meme_sources_report = await get_meme_sources_report(
            user_id, is_ru,
        )

        # ── FIX #7 fallback: random liked meme if LLM didn't pick one ──
        random_liked_meme = None
        if not your_meme_report or not your_meme_report.get("meme_id"):
            liked = [
                d for d in descriptions
                if d.get("reaction_id") == 1
                and d.get("telegram_file_id")
            ]
            if liked:
                pick = random.choice(liked)
                random_liked_meme = {"meme_id": pick["meme_id"]}

        return {
            "bot_usage_report": bot_usage_report,
            "your_meme_report": your_meme_report,
            "random_liked_meme": random_liked_meme,
            "humor_dna_report": humor_dna_report,
            "meme_sources_report": meme_sources_report,
            "prediction": prediction,
        }
    except Exception as e:
        logger.error(
            "Error generating wrapped for user %d: %s",
            user_id, e, exc_info=True,
        )
        return {
            "bot_usage_report": bot_usage_report,
            "your_meme_report": {},
            "random_liked_meme": None,
            "humor_dna_report": "",
            "meme_sources_report": "",
            "prediction": "Лето будет мемным! 🔥",
        }


# ──────────────────────────────────────────────────────────
# CONTENT GENERATORS
# ──────────────────────────────────────────────────────────

async def get_bot_usage_report(user_id: int, is_ru: bool = True):
    user = await get_user_by_id(user_id)
    user_stats = await get_user_stats(user_id)
    if user_stats is None:
        return None

    days = (datetime.datetime.utcnow() - user["created_at"]).days + 1
    sessions = user_stats.get("nsessions", 0)
    memes_sent = user_stats.get("nmemes_sent", 0)
    likes = user_stats.get("nlikes", 0)
    time_sec = user_stats.get("time_spent_sec", 0)

    if likes < 10:
        return None

    like_rate = round(100 * likes / max(memes_sent, 1))

    # ── FIX #2: Better personality labels ──
    if is_ru:
        if like_rate > 60:
            vibe = "Ты лайкаешь больше половины мемов — душа компании 😄"
        elif like_rate > 40:
            vibe = "Ты лайкаешь меньше половины — у тебя есть вкус 👌"
        elif like_rate > 20:
            vibe = "Ты лайкаешь только каждый пятый мем — ты избирательный 🧐"
        else:
            vibe = "Менее 20% мемов удостоены твоего лайка — мем-сноб 🎩"

        # ── FIX #3: "начнём с цифр" intro ──
        report = (
            "📊 <b>Meme Wrapped 2026</b>\n\n"
            "Начнём с цифр.\n\n"
            f"Ты с нами уже <b>{days}</b> дней.\n\n"
            f"🤝 Посмотрел <b>{memes_sent}</b> мемов\n"
            f"👍 Лайкнул <b>{likes}</b> из них "
            f"(<b>{like_rate}%</b>)\n"
            f"👋 Заходил <b>{sessions}</b> раз\n"
        )
    else:
        if like_rate > 60:
            vibe = "You like most memes — life of the party 😄"
        elif like_rate > 40:
            vibe = "Less than half get your like — you have taste 👌"
        elif like_rate > 20:
            vibe = "Only every 5th meme gets a like — selective 🧐"
        else:
            vibe = "Less than 20% worthy — meme snob 🎩"

        report = (
            "📊 <b>Meme Wrapped 2026</b>\n\n"
            "Let's start with the numbers.\n\n"
            f"You've been with us for <b>{days}</b> days.\n\n"
            f"🤝 Seen <b>{memes_sent}</b> memes\n"
            f"👍 Liked <b>{likes}</b> of them "
            f"(<b>{like_rate}%</b>)\n"
            f"👋 Opened the bot <b>{sessions}</b> times\n"
        )

    if time_sec > 0:
        if time_sec < 60:
            t = f"{time_sec} сек" if is_ru else f"{time_sec} sec"
        elif time_sec < 3600:
            m, s = time_sec // 60, time_sec % 60
            t = f"{m} мин {s} сек" if is_ru else f"{m}m {s}s"
        else:
            h = time_sec // 3600
            t = f"больше {h} часов 😳" if is_ru else f"over {h}h 😳"
        emoji = "🕒" if is_ru else "🕒"
        report += f"{emoji} {'В боте' if is_ru else 'Spent'} <b>{t}</b>\n"

    report += f"\n<i>{vibe}</i>"
    return report


async def get_meme_sources_report(user_id: int, is_ru: bool = True):
    """Top 3 meme sources based on user's likes."""
    sources = await get_most_liked_meme_source_urls(user_id, limit=3)
    if not sources:
        return ""

    src_list = "\n".join(f"▪️ {s['url']}" for s in sources)

    if is_ru:
        return (
            "📡 <b>Твои топ-3 мем-паблика:</b>\n\n"
            "По твоим лайкам я вижу, что тебе зайдут:\n\n"
            f"{src_list}"
        )
    return (
        "📡 <b>Your top 3 meme sources:</b>\n\n"
        "Based on your likes, you'd enjoy:\n\n"
        f"{src_list}"
    )


async def get_your_meme_report(
    descriptions: list, is_ru: bool = True,
) -> dict:
    """LLM picks the meme that represents the user."""
    liked = [
        d for d in descriptions
        if d.get("reaction_id") == 1 and d.get("description")
    ]
    if not liked:
        return {}

    meme_texts = "\n".join(
        f"[{i}] {d['description']}" for i, d in enumerate(liked[:20])
    )

    # ── FIX #9: Use disliked memes as context ──
    disliked = [
        d for d in descriptions
        if d.get("reaction_id") == 2 and d.get("description")
    ]
    dislike_context = ""
    if disliked:
        dislike_texts = "\n".join(
            d["description"] for d in disliked[:5]
        )
        dislike_context = (
            f"\n\nМемы, которые этот человек НЕ оценил:\n{dislike_texts}"
        )

    prompt = f"""Ты друг, который анализирует чьё-то чувство юмора по мемам.

Вот мемы, которые этот человек лайкнул:
{meme_texts}
{dislike_context}

Выбери ОДИН мем, который лучше всего олицетворяет этого человека.
Не самый смешной — а тот, который раскрывает что-то настоящее про характер.

Верни JSON: {{"meme_index": N, "reason": "..."}}

Правила для reason:
- Пиши как друг, который подкалывает за столом
- Ссылайся на конкретный мем (не размыто)
- Раскрой что-то про человека, а не про мем
- Максимум 2 предложения, коротко и по делу
- Пиши просто, как будто записываешь голосовое"""

    if not is_ru:
        prompt += "\nAnswer in English."

    result = await call_chatgpt_json(prompt)
    if not result or "meme_index" not in result:
        return {}

    idx = result["meme_index"]
    if 0 <= idx < len(liked):
        return {
            "meme_id": liked[idx]["meme_id"],
            "reason": result.get("reason", ""),
        }
    return {}


async def get_humor_dna_report(
    descriptions: list, is_ru: bool = True,
) -> str:
    """LLM generates humor DNA categories."""
    # ── FIX #9: Explicitly mark liked vs disliked ──
    liked_texts = "\n".join(
        f"✅ {d.get('description', d.get('ocr_text', ''))}"
        for d in descriptions[:30]
        if d.get("reaction_id") == 1
    )
    disliked_texts = "\n".join(
        f"❌ {d.get('description', d.get('ocr_text', ''))}"
        for d in descriptions[:30]
        if d.get("reaction_id") == 2
    )

    prompt = f"""Ты — мем-психолог. Поставь диагноз чувству юмора человека.

Мемы, которые он ЛАЙКНУЛ (✅):
{liked_texts}

Мемы, которые он СКИПНУЛ (❌):
{disliked_texts}

Верни JSON:
{{"categories": [{{"name": "...", "pct": N}}, ...], "summary": "..."}}

Правила:
- РОВНО 3 категории
- Названия: конкретные, прикольные, 2-3 слова максимум
- Проценты примерно в сумме дают 100
- summary: одно предложение, как будто друг говорит голосовым
- Обрати внимание на то, что НЕ понравилось — это тоже важно
- Пиши на русском

Хорошие названия: "Абсурд", "Жиза", "Депрессивный позитив", \
"Токсичная ностальгия", "Офисный ад"
Плохие: "Юмор", "Мемы", "Смешное", "Разное\""""

    if not is_ru:
        prompt += "\nCategory names and summary in English."

    result = await call_chatgpt_json(prompt)
    if not result or "categories" not in result:
        return ""

    categories = result["categories"]
    summary = result.get("summary", "")

    def make_bar(pct: int) -> str:
        filled = round(pct / 10)
        return "█" * filled + "░" * (10 - filled)

    header = (
        "🧬 <b>Твоя ДНК юмора:</b>\n"
        if is_ru else "🧬 <b>Your Humor DNA:</b>\n"
    )
    lines = [header]
    # ── FIX #4: percentage on bar line, name on next line ──
    for cat in categories[:3]:
        pct = min(100, max(0, cat.get("pct", 50)))
        name = cat.get("name", "???")
        bar = make_bar(pct)
        lines.append(f"{bar} {pct}%\n{name}")

    # ── FIX #5: Summary should be simple, like a voice message ──
    if summary:
        lines.append(f"\n<i>{summary}</i>")

    return "\n".join(lines)


async def get_prediction(
    descriptions: list, is_ru: bool = True,
) -> str:
    """LLM generates a fun summer prediction."""
    desc_sample = "\n".join(
        d.get("description", d.get("ocr_text", ""))
        for d in descriptions[:10]
        if d.get("description") or d.get("ocr_text")
    )

    # ── FIX #6: Simple language, like a voice message (Durov style) ──
    prompt = f"""Вот мемы, которые нравятся человеку:

{desc_sample}

Придумай смешное предсказание на лето 2026 для этого человека.

Правила:
- Одно-два предложения, максимум
- Пиши просто, как будто записываешь голосовое другу
- Должно быть конкретно и абсурдно, но понятно с первого раза
- Ссылайся на вкус в мемах (что именно лайкал)
- НЕ пиши сложными конструкциями, НЕ используй метафоры
- Пример тона: "короче летом ты скорее всего будешь..."

Только текст предсказания, без кавычек и пояснений."""

    if not is_ru:
        prompt = f"""Based on these meme preferences:

{desc_sample}

Write a funny, absurd summer 2026 prediction for this person.
One sentence, casual tone, like a voice message to a friend.
Reference their actual meme taste. No metaphors, keep it simple."""

    try:
        return await call_chatgpt(prompt)
    except Exception:
        return (
            "Летом ты будешь пересылать мемы вместо работы 🔥"
            if is_ru else "Your summer will be full of memes 🔥"
        )
