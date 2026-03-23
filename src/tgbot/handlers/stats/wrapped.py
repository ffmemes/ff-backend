import datetime
import json
import logging
import random

from openai import AsyncOpenAI
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from src.config import settings
from src.redis import get_user_wrapped, set_user_wrapped
from src.stats.service import (
    get_meme_descriptions_for_wrapped,
    get_most_liked_meme_source_urls,
    get_top_meme_source_urls,
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


# ──────────────────────────────────────────────────────────
# LLM HELPERS
# ──────────────────────────────────────────────────────────

async def call_deepseek(prompt: str) -> str:
    """Single DeepSeek call — cheap and fast."""
    client = AsyncOpenAI(
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
    )
    response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "user", "content": prompt},
        ],
        max_tokens=1500,
        temperature=0.9,
    )
    return response.choices[0].message.content


def parse_json_from_llm(raw: str) -> dict | None:
    """Extract JSON from LLM response, handling markdown fences."""
    content = raw.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    if content.startswith("json"):
        content = content[4:].strip()
    try:
        return json.loads(content)
    except Exception:
        return None


# ──────────────────────────────────────────────────────────
# SQL-ONLY INSIGHTS (no LLM needed)
# ──────────────────────────────────────────────────────────

async def get_reaction_speed_insight(user_id: int) -> dict:
    """Average reaction time + percentile. Pure SQL."""
    from sqlalchemy import text

    from src.database import fetch_one

    row = await fetch_one(text("""
        WITH user_speed AS (
            SELECT AVG(
                EXTRACT(EPOCH FROM (reacted_at - sent_at))
            ) AS avg_sec
            FROM user_meme_reaction
            WHERE user_id = :user_id
              AND reacted_at IS NOT NULL
              AND sent_at IS NOT NULL
              AND EXTRACT(EPOCH FROM (reacted_at - sent_at)) > 0
              AND EXTRACT(EPOCH FROM (reacted_at - sent_at)) < 120
        ),
        all_speeds AS (
            SELECT user_id, AVG(
                EXTRACT(EPOCH FROM (reacted_at - sent_at))
            ) AS avg_sec
            FROM user_meme_reaction
            WHERE reacted_at IS NOT NULL
              AND sent_at IS NOT NULL
              AND EXTRACT(EPOCH FROM (reacted_at - sent_at)) > 0
              AND EXTRACT(EPOCH FROM (reacted_at - sent_at)) < 120
            GROUP BY user_id
            HAVING COUNT(*) >= 20
        )
        SELECT
            (SELECT avg_sec FROM user_speed) AS avg_sec,
            (SELECT ROUND(100.0 * COUNT(*) FILTER (
                WHERE avg_sec > (SELECT avg_sec FROM user_speed)
             ) / NULLIF(COUNT(*), 0))
             FROM all_speeds) AS faster_than_pct
    """), {"user_id": user_id})

    if not row or row["avg_sec"] is None:
        return {}
    return {
        "avg_sec": round(float(row["avg_sec"]), 1),
        "faster_than_pct": int(row["faster_than_pct"] or 50),
    }


async def get_peak_hour_insight(user_id: int) -> dict:
    """When user is most active. Pure SQL."""
    from sqlalchemy import text

    from src.database import fetch_one

    row = await fetch_one(text("""
        SELECT
            EXTRACT(HOUR FROM reacted_at) AS peak_hour,
            COUNT(*) AS cnt
        FROM user_meme_reaction
        WHERE user_id = :user_id
          AND reacted_at IS NOT NULL
        GROUP BY 1
        ORDER BY 2 DESC
        LIMIT 1
    """), {"user_id": user_id})

    if not row:
        return {}
    hour = int(row["peak_hour"])
    if hour >= 0 and hour < 6:
        label = "ночной скроллер 🌙"
    elif hour < 10:
        label = "утренний мемолюб ☀️"
    elif hour < 14:
        label = "дневной прокрастинатор 💼"
    elif hour < 18:
        label = "послеобеденный залипатель 🍕"
    elif hour < 22:
        label = "вечерний мемоман 🌆"
    else:
        label = "полуночный скроллер 🦉"
    return {"hour": hour, "label": label}


async def get_surprise_meme(user_id: int) -> dict | None:
    """Meme where user liked it but most others didn't. Pure SQL."""
    from sqlalchemy import text

    from src.database import fetch_one

    row = await fetch_one(text("""
        SELECT
            m.id AS meme_id,
            m.type,
            m.telegram_file_id,
            COALESCE(ms.lr_smoothed, 0.5) AS global_lr
        FROM user_meme_reaction umr
        JOIN meme m ON m.id = umr.meme_id
        LEFT JOIN meme_stats ms ON ms.meme_id = m.id
        WHERE umr.user_id = :user_id
          AND umr.reaction_id = 1
          AND m.telegram_file_id IS NOT NULL
          AND COALESCE(ms.lr_smoothed, 0.5) < 0.35
          AND COALESCE(ms.nmemes_sent, 0) >= 10
        ORDER BY ms.lr_smoothed ASC
        LIMIT 1
    """), {"user_id": user_id})

    if not row:
        return None
    return {
        "meme_id": row["meme_id"],
        "type": row["type"],
        "telegram_file_id": row["telegram_file_id"],
        "global_lr": round(float(row["global_lr"]) * 100),
    }


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

    if not await check_if_user_chat_member(
        context.bot, user_id, TELEGRAM_CHANNEL_RU_CHAT_ID,
    ):
        return await update.message.reply_text(
            f"Статистика доступна только подписчикам нашего канала 😉\n\n"
            f"Подпишись:\n{TELEGRAM_CHANNEL_RU_LINK}"
        )

    user_wrapped = await get_user_wrapped(user_id)
    if user_wrapped and not user_wrapped.get("lock"):
        return await handle_wrapped_button(update, context)
    if user_wrapped and user_wrapped.get("lock"):
        return

    # Instant welcome with fun buttons
    await update.effective_chat.send_message(
        text=(
            "🎁 Мы подготовили глубокий анализ "
            "твоего чувства юмора.\n\n"
            "Хочешь посмотреть?"
        ),
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "ДА", callback_data="wrapped_go",
                ),
                InlineKeyboardButton(
                    "ПОСМОТРЕТЬ", callback_data="wrapped_go",
                ),
            ]
        ]),
    )


async def handle_wrapped_go(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """User pressed ДА/ПОСМОТРЕТЬ — generate everything."""
    if update.callback_query:
        await update.callback_query.answer()

    user_id = update.effective_user.id

    user_wrapped = await get_user_wrapped(user_id)
    if user_wrapped and not user_wrapped.get("lock"):
        return await handle_wrapped_button(update, context)
    if user_wrapped and user_wrapped.get("lock"):
        return

    # Show typing
    try:
        await context.bot.send_chat_action(
            chat_id=user_id, action=ChatAction.TYPING,
        )
    except Exception:
        pass

    # Check minimums
    user_stats_data = await get_user_stats(user_id)
    if not user_stats_data:
        return await update.effective_chat.send_message(
            "Маловато ты пользовался ботом 😅\n"
            "Посмотри побольше мемов! /start"
        )

    nmemes_sent = user_stats_data.get("nmemes_sent", 0)
    if nmemes_sent < WRAPPED_MIN_REACTIONS:
        remaining = WRAPPED_MIN_REACTIONS - nmemes_sent
        return await update.effective_chat.send_message(
            f"Посмотри ещё {remaining} мемов и возвращайся! /start"
        )

    descriptions = await get_meme_descriptions_for_wrapped(
        user_id, limit=40,
    )
    if len(descriptions) < WRAPPED_MIN_DESCRIPTIONS:
        return await update.effective_chat.send_message(
            "Мы ещё анализируем твои мемы... 🔬\n"
            "Попробуй через пару часов! /start"
        )

    user = await get_user_by_id(user_id)
    is_ru = get_user_interface_language(user) == "ru"

    # Send stats slide immediately
    stats_report = await get_bot_usage_report(user_id, is_ru)
    if stats_report is None:
        return await update.effective_chat.send_message(
            "Маловато данных 😅 Жми /start"
        )

    await update.effective_chat.send_message(
        text=stats_report,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(
                "Дальше →", callback_data="wrapped_1",
            )]]
        ),
    )

    # Generate everything in background (1 DeepSeek call + SQL)
    data = await generate_wrapped_data(
        user_id, descriptions, is_ru, stats_report,
    )
    if data:
        await set_user_wrapped(user_id, data)


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

    # Slide 0: Stats (re-entry from cache)
    if key == 0:
        await update.effective_chat.send_message(
            text=user_wrapped["stats_report"],
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(
                    "Дальше →", callback_data="wrapped_1",
                )]]
            ),
        )

    # Slide 1: Мем, который олицетворяет тебя
    if key == 1:
        meme_info = user_wrapped.get("your_meme")
        sent = False
        if meme_info and meme_info.get("meme_id"):
            meme_data = await get_meme_by_id(meme_info["meme_id"])
            if meme_data and meme_data.get("telegram_file_id"):
                caption = meme_info.get(
                    "caption", "🎯 Этот мем — это ты",
                )
                meme = MemeData(
                    id=meme_data["id"],
                    type=meme_data["type"],
                    telegram_file_id=meme_data["telegram_file_id"],
                    caption=caption,
                )
                await send_new_message_with_meme(
                    context.bot,
                    update.effective_user.id,
                    meme,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton(
                            "Дальше →", callback_data="wrapped_2",
                        )]]
                    ),
                )
                sent = True
        if not sent:
            key = 2  # skip to next

    # Slide 2: ДНК юмора + personality roast
    if key == 2:
        text_msg = user_wrapped.get("humor_report", "")
        if text_msg:
            await update.effective_chat.send_message(
                text=text_msg,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(
                        "Дальше →", callback_data="wrapped_3",
                    )]]
                ),
            )
        else:
            key = 3

    # Slide 3: Anti-profile (what your dislikes say)
    if key == 3:
        anti = user_wrapped.get("anti_profile", "")
        if anti:
            await update.effective_chat.send_message(
                text=anti,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(
                        "Дальше →", callback_data="wrapped_4",
                    )]]
                ),
            )
        else:
            key = 4

    # Slide 4: Top 3 sources + speed + peak hour
    if key == 4:
        await update.effective_chat.send_message(
            text=user_wrapped.get("stats_extra", ""),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(
                    "Финалочка →", callback_data="wrapped_5",
                )]]
            ),
        )

    # Slide 5: Prediction + finale
    if key == 5:
        prediction = user_wrapped.get("prediction", "")
        await update.effective_chat.send_message(
            text=(
                "🔮 <b>Предсказание на лето 2026:</b>\n\n"
                f"<i>{prediction}</i>\n\n"
                "❤️ Спасибо за то, что пользуешься ботом.\n"
                "Продолжай смотреть мемы и пересылай друзьям!\n\n"
                "🍔 @ffmemesbot\n\n/start"
            ),
            parse_mode="HTML",
        )


async def handle_wrapped_clear(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
) -> None:
    user_id = update.effective_user.id
    user = await get_user_by_id(user_id)
    if not user or user.get("type") not in ("moderator", "admin"):
        return
    from src.redis import redis_client
    await redis_client.delete(f"wrapped:{user_id}")
    await update.message.reply_text("Wrapped cache cleared ✓ /wrapped")


# ──────────────────────────────────────────────────────────
# GENERATION (1 DeepSeek call + SQL)
# ──────────────────────────────────────────────────────────

async def generate_wrapped_data(
    user_id: int,
    descriptions: list,
    is_ru: bool,
    stats_report: str,
) -> dict | None:
    """One DeepSeek call + SQL queries → all wrapped data."""
    await set_user_wrapped(user_id, {"lock": True}, ttl=300)

    try:
        # 1. Build meme context for DeepSeek
        liked = [
            d for d in descriptions if d.get("reaction_id") == 1
        ]
        disliked = [
            d for d in descriptions if d.get("reaction_id") == 2
        ]

        liked_texts = "\n".join(
            f"[{i}] ✅ {d.get('description') or d.get('ocr_text', '')}"
            for i, d in enumerate(liked[:25])
        )
        disliked_texts = "\n".join(
            f"❌ {d.get('description') or d.get('ocr_text', '')}"
            for d in disliked[:15]
        )

        # 2. ONE DeepSeek call for everything (run first!)
        prompt = _build_mega_prompt(liked_texts, disliked_texts, is_ru)
        raw = await call_deepseek(prompt)
        parsed = parse_json_from_llm(raw)

        if not parsed:
            logger.warning(
                "DeepSeek JSON failed for user %d. Raw: %s",
                user_id, raw[:300],
            )
            parsed = {}

        # 3. Determine "your meme"
        your_meme = _pick_meme_from_result(parsed, liked)

        # 4. SQL insights (safe — each wrapped in try/except)
        try:
            speed = await get_reaction_speed_insight(user_id)
        except Exception as e:
            logger.warning("Speed insight failed: %s", e)
            speed = {}
        try:
            peak = await get_peak_hour_insight(user_id)
        except Exception as e:
            logger.warning("Peak hour insight failed: %s", e)
            peak = {}
        try:
            surprise = await get_surprise_meme(user_id)
        except Exception as e:
            logger.warning("Surprise meme failed: %s", e)
            surprise = None
        try:
            sources_report = await _build_sources_report(user_id, is_ru)
        except Exception as e:
            logger.warning("Sources report failed: %s", e)
            sources_report = ""

        # 5. Build all slide content
        humor_report = _build_humor_slide(parsed, is_ru)
        anti_profile = _build_anti_profile_slide(parsed, is_ru)
        stats_extra = _build_stats_extra_slide(
            sources_report, speed, peak, is_ru,
        )
        prediction = parsed.get(
            "prediction",
            "Летом ты будешь пересылать мемы вместо работы 🔥",
        )

        # Use surprise meme if LLM didn't pick one
        if not your_meme and surprise:
            your_meme = {
                "meme_id": surprise["meme_id"],
                "caption": (
                    f"🎲 Этот мем лайкнул только ты "
                    f"(глобальный лайк-рейт: {surprise['global_lr']}%)"
                ),
            }

        # Random liked meme as last resort
        if not your_meme and liked:
            pick = random.choice(liked[:10])
            your_meme = {
                "meme_id": pick["meme_id"],
                "caption": "🎲 А вот мем, который тебе зашёл:",
            }

        return {
            "stats_report": stats_report,
            "your_meme": your_meme,
            "humor_report": humor_report,
            "anti_profile": anti_profile,
            "stats_extra": stats_extra,
            "prediction": prediction,
        }

    except Exception as e:
        logger.error(
            "Wrapped generation failed for user %d: %s",
            user_id, e, exc_info=True,
        )
        return {
            "stats_report": stats_report,
            "your_meme": None,
            "humor_report": "",
            "anti_profile": "",
            "stats_extra": "",
            "prediction": "Летом ты будешь пересылать мемы вместо работы 🔥",
        }


def _build_mega_prompt(
    liked_texts: str, disliked_texts: str, is_ru: bool,
) -> str:
    """One prompt that returns all LLM content as JSON."""
    return f"""Ты мем-психолог. Проанализируй чувство юмора человека.

ЛАЙКНУТЫЕ МЕМЫ:
{liked_texts}

СКИПНУТЫЕ МЕМЫ:
{disliked_texts}

Верни JSON (и только JSON, без текста до/после):
{{
  "meme_index": число (какой лайкнутый мем [индекс] лучше олицетворяет этого человека),
  "meme_caption": "почему этот мем — это он (2 предложения, как подкол от друга)",
  "humor_dna": [
    {{"name": "название категории", "pct": число}},
    {{"name": "название категории", "pct": число}},
    {{"name": "название категории", "pct": число}}
  ],
  "humor_roast": "3 пункта, каждый 1-2 предложения, как голосовое другу",
  "anti_profile": "2-3 предложения что НЕ любит и почему, как голосовое",
  "prediction": "предсказание на лето 2026, 1-2 предложения, абсурдное"
}}

Правила:
- Названия категорий: конкретные и прикольные, 2-3 слова
- humor_roast: три абзаца через \\n\\n, каждый 1-2 предложения
- Всё на русском
- Пиши просто, как будто записываешь голосовое
- Обязательно используй знания о скипнутых мемах
- Проценты в humor_dna примерно дают 100"""


def _pick_meme_from_result(parsed: dict, liked: list) -> dict | None:
    """Extract meme selection from DeepSeek result."""
    idx = parsed.get("meme_index")
    caption = parsed.get(
        "meme_caption", "🎯 Этот мем олицетворяет тебя",
    )
    if idx is not None and 0 <= idx < len(liked):
        return {
            "meme_id": liked[idx]["meme_id"],
            "caption": f"🎯 Этот мем олицетворяет тебя:\n\n<i>{caption}</i>",
        }
    return None


def _build_humor_slide(parsed: dict, is_ru: bool) -> str:
    """Build humor DNA + roast slide."""
    dna = parsed.get("humor_dna", [])
    roast = parsed.get("humor_roast", "")

    def make_bar(pct: int) -> str:
        filled = round(pct / 10)
        return "█" * filled + "░" * (10 - filled)

    lines = ["🧬 <b>Твоя ДНК юмора:</b>\n"]
    for cat in dna[:3]:
        pct = min(100, max(0, cat.get("pct", 33)))
        name = cat.get("name", "???")
        lines.append(f"{make_bar(pct)} {pct}%\n{name}\n")

    if roast:
        lines.append(f"\n👀 <b>Что я понял про тебя:</b>\n\n{roast}")

    return "\n".join(lines) if len(lines) > 1 else ""


def _build_anti_profile_slide(parsed: dict, is_ru: bool) -> str:
    """Build anti-profile slide (what dislikes reveal)."""
    anti = parsed.get("anti_profile", "")
    if not anti:
        return ""
    return f"🚫 <b>Что говорят твои скипы:</b>\n\n{anti}"


def _build_stats_extra_slide(
    sources_report: str,
    speed: dict,
    peak: dict,
    is_ru: bool,
) -> str:
    """Build stats slide: sources + speed + peak hour."""
    parts = []

    if sources_report:
        parts.append(sources_report)

    if speed:
        avg = speed["avg_sec"]
        pct = speed["faster_than_pct"]
        parts.append(
            f"⚡ <b>Скорость реакции:</b> {avg} сек в среднем\n"
            f"Ты быстрее {pct}% пользователей"
        )

    if peak:
        h = peak["hour"]
        label = peak["label"]
        parts.append(
            f"🕐 <b>Пик активности:</b> {h}:00\n"
            f"Ты — {label}"
        )

    return "\n\n".join(parts) if parts else "📊 Скоро тут будет больше данных!"


async def _build_sources_report(
    user_id: int, is_ru: bool,
) -> str:
    """Top 3 real meme sources (filtered)."""
    sources = await get_most_liked_meme_source_urls(user_id, limit=10)
    real = [
        s for s in (sources or [])
        if s.get("url")
        and not s["url"].startswith("tg://user")
        and ("t.me/" in s["url"] or "vk.com/" in s["url"])
    ]

    if len(real) < 3:
        try:
            top = await get_top_meme_source_urls(limit=5)
            for t in (top or []):
                if (
                    t.get("url")
                    and not t["url"].startswith("tg://user")
                    and t["url"] not in [s["url"] for s in real]
                ):
                    real.append(t)
                    if len(real) >= 3:
                        break
        except Exception:
            pass

    if not real:
        return ""

    src_list = "\n".join(f"▪️ {s['url']}" for s in real[:3])
    return (
        f"📡 <b>Твои топ мем-паблики:</b>\n\n{src_list}"
    )


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
# STATS SLIDE
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

    if like_rate > 50:
        vibe = "Ты лайкаешь больше половины мемов — душа компании 😄"
    elif like_rate > 30:
        vibe = "Лайкаешь примерно каждый третий — у тебя есть вкус 👌"
    elif like_rate > 15:
        vibe = "Только каждый пятый удостоен лайка — избирательный 🧐"
    else:
        vibe = "Менее 15% мемов достойны — мем-сноб 🎩"

    report = (
        "📊 <b>Meme Wrapped 2026</b>\n\n"
        "Начнём с цифр.\n\n"
        f"Ты с нами уже <b>{days}</b> дней.\n\n"
        f"🤝 Посмотрел <b>{memes_sent}</b> мемов\n"
        f"👍 Лайкнул <b>{likes}</b> из них "
        f"(<b>{like_rate}%</b>)\n"
        f"👋 Заходил <b>{sessions}</b> раз\n"
    )

    if time_sec > 0:
        if time_sec < 60:
            t = f"{time_sec} сек"
        elif time_sec < 3600:
            t = f"{time_sec // 60} мин {time_sec % 60} сек"
        else:
            t = f"больше {time_sec // 3600} часов 😳"
        report += f"🕒 В боте <b>{t}</b>\n"

    report += f"\n<i>{vibe}</i>"
    return report
