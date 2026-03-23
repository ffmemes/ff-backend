import asyncio
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


# ── LLM ──────────────────────────────────────────────────

async def call_deepseek(prompt: str) -> str:
    client = AsyncOpenAI(
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
    )
    resp = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1500,
        temperature=0.9,
    )
    return resp.choices[0].message.content


def parse_json_from_llm(raw: str) -> dict | None:
    c = raw.strip()
    if c.startswith("```"):
        c = c.split("\n", 1)[1] if "\n" in c else c[3:]
    if c.endswith("```"):
        c = c[:-3]
    c = c.strip()
    if c.startswith("json"):
        c = c[4:].strip()
    try:
        return json.loads(c)
    except Exception:
        return None


# ── SQL INSIGHTS ─────────────────────────────────────────

async def get_reaction_speed_insight(user_id: int) -> dict:
    """Median reaction time, split by like/dislike. Pure SQL."""
    from sqlalchemy import text

    from src.database import fetch_one

    row = await fetch_one(text("""
        WITH reactions AS (
            SELECT
                EXTRACT(EPOCH FROM (reacted_at - sent_at)) AS sec,
                reaction_id
            FROM user_meme_reaction
            WHERE user_id = :user_id
              AND reacted_at IS NOT NULL AND sent_at IS NOT NULL
              AND EXTRACT(EPOCH FROM (reacted_at - sent_at))
                  BETWEEN 0.5 AND 120
        )
        SELECT
            PERCENTILE_CONT(0.5) WITHIN GROUP (
                ORDER BY sec
            ) AS median_sec,
            PERCENTILE_CONT(0.5) WITHIN GROUP (
                ORDER BY sec
            ) FILTER (WHERE reaction_id = 1) AS median_like,
            PERCENTILE_CONT(0.5) WITHIN GROUP (
                ORDER BY sec
            ) FILTER (WHERE reaction_id = 2) AS median_dislike
        FROM reactions
    """), {"user_id": user_id})

    if not row or row["median_sec"] is None:
        return {}
    return {
        "median_sec": round(float(row["median_sec"]), 1),
        "median_like": round(float(row["median_like"] or 0), 1),
        "median_dislike": round(float(row["median_dislike"] or 0), 1),
    }


async def get_peak_hour_insight(user_id: int, is_ru: bool = True) -> dict:
    """Peak activity hour. Moscow time for RU, UTC for EN."""
    from sqlalchemy import text

    from src.database import fetch_one

    # UTC+3 for Russian users
    tz_offset = 3 if is_ru else 0
    row = await fetch_one(text(f"""
        SELECT
            EXTRACT(HOUR FROM reacted_at + interval '{tz_offset} hours')
                AS peak_hour,
            COUNT(*) AS cnt
        FROM user_meme_reaction
        WHERE user_id = :user_id AND reacted_at IS NOT NULL
        GROUP BY 1 ORDER BY 2 DESC LIMIT 1
    """), {"user_id": user_id})

    if not row:
        return {}
    hour = int(row["peak_hour"])
    labels = {
        (0, 6): "ночной скроллер 🌙",
        (6, 10): "утренний мемолюб ☀️",
        (10, 14): "дневной прокрастинатор 💼",
        (14, 18): "послеобеденный залипатель 🍕",
        (18, 22): "вечерний мемоман 🌆",
        (22, 24): "полуночный скроллер 🦉",
    }
    label = next(
        (v for (lo, hi), v in labels.items() if lo <= hour < hi),
        "мемоман",
    )
    tz_label = "МСК" if is_ru else "UTC"
    return {"hour": hour, "label": label, "tz": tz_label}


async def get_surprise_meme(user_id: int) -> dict | None:
    """Meme user liked but most others didn't."""
    from sqlalchemy import text

    from src.database import fetch_one

    row = await fetch_one(text("""
        SELECT m.id AS meme_id, m.type, m.telegram_file_id,
               ROUND(COALESCE(ms.lr_smoothed, 0.5) * 100)
                   AS global_lr_pct
        FROM user_meme_reaction umr
        JOIN meme m ON m.id = umr.meme_id
        LEFT JOIN meme_stats ms ON ms.meme_id = m.id
        WHERE umr.user_id = :user_id
          AND umr.reaction_id = 1
          AND m.telegram_file_id IS NOT NULL
          AND COALESCE(ms.lr_smoothed, 0.5) < 0.35
          AND COALESCE(ms.nmemes_sent, 0) >= 10
        ORDER BY ms.lr_smoothed ASC LIMIT 1
    """), {"user_id": user_id})
    if not row:
        return None
    return dict(row)


# ── MAIN HANDLER ─────────────────────────────────────────

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

    cached = await get_user_wrapped(user_id)
    if cached and not cached.get("lock"):
        return await handle_wrapped_button(update, context)
    if cached and cached.get("lock"):
        return

    # Check conditions BEFORE showing welcome
    user_stats_data = await get_user_stats(user_id)
    if not user_stats_data:
        return await update.message.reply_text(
            "Маловато ты пользовался ботом 😅 /start"
        )
    nmemes_sent = user_stats_data.get("nmemes_sent", 0)
    if nmemes_sent < WRAPPED_MIN_REACTIONS:
        remaining = WRAPPED_MIN_REACTIONS - nmemes_sent
        return await update.message.reply_text(
            f"Посмотри ещё {remaining} мемов и возвращайся! /start"
        )
    descriptions = await get_meme_descriptions_for_wrapped(
        user_id, limit=40,
    )
    if len(descriptions) < WRAPPED_MIN_DESCRIPTIONS:
        return await update.message.reply_text(
            "Мы ещё анализируем твои мемы... 🔬\n"
            "Попробуй через пару часов! /start"
        )

    # ── START DEEPSEEK EARLY (while user reads welcome) ──
    user = await get_user_by_id(user_id)
    is_ru = get_user_interface_language(user) == "ru"
    stats_report = await get_bot_usage_report(
        user_id, user_stats_data, user, is_ru,
    )
    asyncio.create_task(
        _generate_and_cache(
            user_id, descriptions, is_ru, stats_report or "",
        )
    )

    # Welcome message
    await update.effective_chat.send_message(
        text=(
            "🎁 Мы подготовили глубокий анализ "
            "твоего чувства юмора.\n\n"
            "Хочешь посмотреть?"
        ),
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("ДА", callback_data="wrapped_go"),
            InlineKeyboardButton(
                "ПОСМОТРЕТЬ", callback_data="wrapped_go",
            ),
        ]]),
    )


async def handle_wrapped_go(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """ДА / ПОСМОТРЕТЬ pressed — show stats slide."""
    if update.callback_query:
        await update.callback_query.answer()

    user_id = update.effective_user.id
    try:
        await context.bot.send_chat_action(
            chat_id=user_id, action=ChatAction.TYPING,
        )
    except Exception:
        pass

    cached = await get_user_wrapped(user_id)
    if cached and not cached.get("lock"):
        return await handle_wrapped_button(update, context)

    # Still generating — show stats from cache (partial)
    if cached and cached.get("lock"):
        stats = cached.get("stats_report")
        if stats:
            return await update.effective_chat.send_message(
                text=stats,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(
                        "Дальше →", callback_data="wrapped_1",
                    )]]
                ),
            )
        # Still no stats — tell user to wait
        await update.effective_chat.send_message(
            "⏳ Анализирую твои мемы... нажми Дальше через пару секунд"
        )
        return

    # No cache at all — shouldn't happen, but handle gracefully
    await update.effective_chat.send_message(
        "Попробуй /wrapped ещё раз"
    )


async def _generate_and_cache(
    user_id: int, descriptions: list,
    is_ru: bool, stats_report: str,
):
    """Background: generate all data and save to cache."""
    try:
        # Save stats immediately so ДА can show them
        await set_user_wrapped(
            user_id,
            {"lock": True, "stats_report": stats_report},
            ttl=300,
        )
        logger.info("[wrapped] starting generation for %d", user_id)

        data = await generate_wrapped_data(
            user_id, descriptions, is_ru, stats_report,
        )
        if data:
            await set_user_wrapped(user_id, data)
            logger.info("[wrapped] done for %d", user_id)
        else:
            logger.warning("[wrapped] returned None for %d", user_id)
    except Exception as e:
        logger.error("[wrapped] bg error for %d: %s", user_id, e)
        from src.redis import redis_client
        await redis_client.delete(f"wrapped:{user_id}")


# ── SLIDE NAVIGATION ─────────────────────────────────────

async def handle_wrapped_button(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
) -> None:
    user_id = update.effective_user.id
    uw = await get_user_wrapped(user_id)
    if not uw:
        logger.warning("[wrapped] no cache for %d", user_id)
        return

    if uw.get("lock"):
        if update.callback_query:
            await update.callback_query.answer(
                "⏳ Ещё генерирую... подожди пару секунд",
                show_alert=False,
            )
        return

    if update.callback_query:
        await update.callback_query.answer()
        key = int(
            update.callback_query.data.replace("wrapped_", ""),
        )
    else:
        key = 0

    logger.info("[wrapped] user=%d key=%d", user_id, key)

    try:
        await context.bot.send_chat_action(
            chat_id=user_id, action=ChatAction.TYPING,
        )
    except Exception:
        pass

    try:
        await _show_slide(update, context, uw, key, user_id)
    except Exception as e:
        logger.error(
            "[wrapped] slide %d error for %d: %s",
            key, user_id, e, exc_info=True,
        )
        # Try to send next slide as fallback
        try:
            if key < 5:
                await _show_slide(
                    update, context, uw, key + 1, user_id,
                )
        except Exception:
            pass


async def _show_slide(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    uw: dict, key: int, user_id: int,
) -> None:
    """Send a single slide. Extracted for error isolation."""

    # ── Slides ──
    if key == 0:
        await update.effective_chat.send_message(
            text=uw.get("stats_report", "📊"),
            parse_mode="HTML",
            reply_markup=_next_btn("wrapped_1"),
        )

    # Slide 1: Your meme
    if key == 1:
        sent = False
        meme_info = uw.get("your_meme")
        try:
            if meme_info and meme_info.get("meme_id"):
                md = await get_meme_by_id(meme_info["meme_id"])
                if md and md.get("telegram_file_id"):
                    meme = MemeData(
                        id=md["id"], type=md["type"],
                        telegram_file_id=md["telegram_file_id"],
                        caption=meme_info.get(
                            "caption", "🎯 Этот мем — это ты",
                        ),
                    )
                    await send_new_message_with_meme(
                        context.bot, user_id, meme,
                        reply_markup=_next_btn("wrapped_2"),
                    )
                    sent = True
        except Exception as e:
            logger.error("[wrapped] meme slide error: %s", e)
        if not sent:
            key = 2

    # Slide 2: Humor DNA + roast
    if key == 2:
        txt = uw.get("humor_report", "")
        if txt:
            try:
                await update.effective_chat.send_message(
                    text=txt, parse_mode="HTML",
                    reply_markup=_next_btn("wrapped_3"),
                )
            except Exception as e:
                logger.error("[wrapped] humor slide error: %s", e)
                key = 3
        else:
            key = 3

    # Slide 3: Anti-profile
    if key == 3:
        txt = uw.get("anti_profile", "")
        if txt:
            try:
                await update.effective_chat.send_message(
                    text=txt, parse_mode="HTML",
                    reply_markup=_next_btn("wrapped_4"),
                )
            except Exception as e:
                logger.error("[wrapped] anti slide error: %s", e)
                key = 4
        else:
            key = 4

    # Slide 4: Sources + speed + peak
    if key == 4:
        txt = uw.get("stats_extra", "")
        if txt:
            try:
                await update.effective_chat.send_message(
                    text=txt, parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton(
                            "Финалочка →",
                            callback_data="wrapped_5",
                        )]]
                    ),
                )
            except Exception as e:
                logger.error("[wrapped] stats extra error: %s", e)
                key = 5
        else:
            key = 5

    # Slide 5: Prediction + referral
    if key == 5:
        pred = uw.get("prediction", "")
        await update.effective_chat.send_message(
            text=(
                "🔮 <b>Предсказание на лето 2026:</b>\n\n"
                f"<i>{pred}</i>\n\n"
                "❤️ Спасибо за то, что пользуешься ботом.\n\n"
                "Перешли ссылку другу — пусть тоже узнает "
                "свой мем-профиль 👇"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "📤 Отправить другу",
                    url="https://t.me/ffmemesbot?start=wrapped",
                ),
            ]]),
        )


def _next_btn(callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Дальше →", callback_data=callback)]]
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
    await update.message.reply_text("Cache cleared ✓ /wrapped")


# ── GENERATION ───────────────────────────────────────────

async def generate_wrapped_data(
    user_id: int, descriptions: list,
    is_ru: bool, stats_report: str,
) -> dict | None:
    await set_user_wrapped(
        user_id,
        {"lock": True, "stats_report": stats_report},
        ttl=300,
    )

    try:
        liked = [d for d in descriptions if d.get("reaction_id") == 1]
        disliked = [d for d in descriptions if d.get("reaction_id") == 2]

        liked_texts = "\n".join(
            f"[{i}] ✅ {d.get('description') or d.get('ocr_text', '')}"
            for i, d in enumerate(liked[:25])
        )
        disliked_texts = "\n".join(
            f"❌ {d.get('description') or d.get('ocr_text', '')}"
            for d in disliked[:15]
        )

        # ONE DeepSeek call
        prompt = _build_mega_prompt(liked_texts, disliked_texts)
        raw = await call_deepseek(prompt)
        p = parse_json_from_llm(raw)
        if not p:
            logger.warning(
                "DeepSeek JSON failed user %d: %s", user_id, raw[:300],
            )
            p = {}

        your_meme = _pick_meme(p, liked)

        # SQL insights (each safe)
        speed = await _safe(get_reaction_speed_insight(user_id))
        peak = await _safe(get_peak_hour_insight(user_id, is_ru))
        surprise = await _safe(get_surprise_meme(user_id))
        sources = await _safe(_build_sources_report(user_id))

        # Use surprise meme if LLM didn't pick one
        if not your_meme and surprise:
            lr = surprise.get("global_lr_pct", "?")
            your_meme = {
                "meme_id": surprise["meme_id"],
                "caption": (
                    f"🎲 Этот мем лайкнул только ты\n"
                    f"(глобальный лайк-рейт: {lr}%)"
                ),
            }
        if not your_meme and liked:
            pick = random.choice(liked[:10])
            your_meme = {
                "meme_id": pick["meme_id"],
                "caption": "🎲 А вот мем, который тебе зашёл:",
            }

        # Build slides
        # Stats report gets vibe from DeepSeek
        vibe = p.get("vibe", "")
        if vibe and stats_report:
            stats_report = stats_report.replace(
                stats_report.split("\n<i>")[-1] if "\n<i>" in stats_report else "",
                f"\n<i>{vibe}</i>",
            ) if "\n<i>" in stats_report else stats_report + f"\n\n<i>{vibe}</i>"

        return {
            "stats_report": stats_report,
            "your_meme": your_meme,
            "humor_report": _build_humor_slide(p),
            "anti_profile": _build_anti_slide(p),
            "stats_extra": _build_extra_slide(sources, speed, peak),
            "prediction": p.get(
                "prediction",
                "Летом ты будешь листать мемы вместо работы 🔥",
            ),
        }
    except Exception as e:
        logger.error("Wrapped failed user %d: %s", user_id, e, exc_info=True)
        return {
            "stats_report": stats_report,
            "your_meme": None,
            "humor_report": "",
            "anti_profile": "",
            "stats_extra": "",
            "prediction": "Летом ты будешь листать мемы вместо работы 🔥",
        }


async def _safe(coro):
    try:
        return await coro
    except Exception as e:
        logger.warning("Wrapped SQL insight failed: %s", e)
        return {} if not isinstance(e, TypeError) else None


def _build_mega_prompt(liked_texts: str, disliked_texts: str) -> str:
    return f"""Ты мем-психолог. Проанализируй чувство юмора.

ЛАЙКНУТЫЕ МЕМЫ:
{liked_texts}

СКИПНУТЫЕ МЕМЫ:
{disliked_texts}

Верни ТОЛЬКО JSON:
{{
  "vibe": "одно предложение-характеристика этого человека по его мемам, \
как подкол от друга, 10-15 слов",
  "meme_index": число (индекс лайкнутого мема, который олицетворяет),
  "meme_caption": "почему этот мем — это ты (2 предложения, подкол)",
  "humor_dna": [
    {{"name": "категория", "pct": число}},
    {{"name": "категория", "pct": число}},
    {{"name": "категория", "pct": число}}
  ],
  "humor_roast": "3 абзаца через \\n\\n. Каждый 1-2 предложения. \
Пиши смешно, как голосовое другу. Упоминай конкретные мемы. \
Шути, а не ставь диагноз.",
  "anti_profile": "2-3 коротких абзаца через \\n\\n. \
Обращайся на ТЫ: 'ты терпеть не можешь...'. \
Что ТЫ не любишь и почему.",
  "prediction": "предсказание на лето 2026. \
Одно-два предложения. Конкретно, абсурдно, \
как голосовое другу. Без метафор."
}}

Правила:
- Категории: конкретные, прикольные, 2-3 слова
- Проценты примерно дают 100
- Всё на русском
- Пиши просто, как голосовое сообщение
- Anti_profile: обязательно на ТЫ (не в третьем лице)
- Humor_roast: шути, а не ставь приговор"""


def _pick_meme(p: dict, liked: list) -> dict | None:
    idx = p.get("meme_index")
    cap = p.get("meme_caption", "🎯 Этот мем олицетворяет тебя")
    if idx is not None and 0 <= idx < len(liked):
        return {
            "meme_id": liked[idx]["meme_id"],
            "caption": f"🎯 Этот мем олицетворяет тебя:\n\n<i>{cap}</i>",
        }
    return None


def _build_humor_slide(p: dict) -> str:
    dna = p.get("humor_dna", [])
    roast = p.get("humor_roast", "")

    def bar(pct):
        f = round(pct / 10)
        return "█" * f + "░" * (10 - f)

    lines = ["🧬 <b>Твоя ДНК юмора:</b>\n"]
    for c in dna[:3]:
        pct = min(100, max(0, c.get("pct", 33)))
        lines.append(f"{bar(pct)} {pct}%\n{c.get('name', '???')}\n")

    if roast:
        lines.append(f"\n👀 <b>Что я понял про тебя:</b>\n\n{roast}")
    return "\n".join(lines) if len(lines) > 1 else ""


def _build_anti_slide(p: dict) -> str:
    anti = p.get("anti_profile", "")
    if not anti:
        return ""
    return f"🚫 <b>Что говорят твои скипы:</b>\n\n{anti}"


def _build_extra_slide(
    sources: str, speed: dict, peak: dict,
) -> str:
    parts = []
    if sources:
        parts.append(sources)

    if speed:
        med = speed.get("median_sec", 0)
        ml = speed.get("median_like", 0)
        md = speed.get("median_dislike", 0)
        parts.append(
            f"⚡ <b>Скорость реакции:</b> {med} сек\n"
            f"(до лайка: {ml} сек, до скипа: {md} сек)"
        )

    if peak:
        h = peak.get("hour", 0)
        label = peak.get("label", "")
        tz = peak.get("tz", "")
        parts.append(
            f"🕐 <b>Пик активности:</b> {h}:00 {tz}\n"
            f"Ты — {label}"
        )

    return "\n\n".join(parts) if parts else ""


async def _build_sources_report(user_id: int) -> str:
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
    return f"📡 <b>Твои топ мем-паблики:</b>\n\n{src_list}"


# ── STATS SLIDE ──────────────────────────────────────────

async def get_bot_usage_report(
    user_id: int, user_stats: dict, user: dict,
    is_ru: bool = True,
) -> str | None:
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

    # Placeholder vibe — will be replaced by DeepSeek output
    if like_rate > 50:
        vibe = "Лайкаешь больше половины — тебе всё смешно 😄"
    elif like_rate > 30:
        vibe = "Лайкаешь каждый третий — у тебя есть вкус 👌"
    elif like_rate > 15:
        vibe = "Лайкаешь каждый пятый — избирательный 🧐"
    else:
        vibe = "Менее 15% мемов достойны — мем-сноб 🎩"
    report += f"\n<i>{vibe}</i>"
    return report


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
