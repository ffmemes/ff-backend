import asyncio
import datetime
import json
import logging
import random
import sys
from html import escape as html_escape
from urllib.parse import quote

from openai import AsyncOpenAI
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from src.config import settings
from src.localizer import ALMOST_CIS_LANGUAGES
from src.redis import get_user_wrapped, set_user_wrapped
from src.stats.service import (
    get_meme_descriptions_for_wrapped,
    get_most_liked_meme_source_urls,
    get_top_meme_source_urls,
    get_user_stats,
)
from src.storage.schemas import MemeData
from src.tgbot.senders.meme import send_new_message_with_meme
from src.tgbot.service import (
    create_or_update_user,
    get_meme_by_id,
    get_user_by_id,
    get_user_languages,
    save_tg_user,
)
from src.tgbot.utils import (
    check_if_user_follows_related_channel,
    get_related_channel_link,
)

logger = logging.getLogger(__name__)

WRAPPED_MIN_REACTIONS = 30
WRAPPED_MIN_DESCRIPTIONS = 5

LOADING_MESSAGES_RU = [
    "🔬 Анализируем твои мемы...",
    "👀 Смотрим на лайки...",
    "📊 Много же ты листал...",
    "🤖 AI смотрит твои мемы...",
    "🧠 Изучаем твой юмор...",
    "🎭 Определяем твой вайб...",
]

LOADING_MESSAGES_EN = [
    "🔬 Analyzing your memes...",
    "👀 Looking at your likes...",
    "📊 You've scrolled a lot...",
    "🤖 AI is studying your memes...",
    "🧠 Analyzing your humor...",
    "🎭 Figuring out your vibe...",
]

LOADING_BUTTONS_RU = [
    "Готово? →",
    "Проверить →",
    "Ну давай уже →",
    "Уже? →",
    "Ещё раз →",
]

LOADING_BUTTONS_EN = [
    "Ready? →",
    "Check →",
    "C'mon already →",
    "Yet? →",
    "Try again →",
]

ABSURD_CATEGORIES = [
    "бытовая техника",
    "животное",
    "блюдо/еда",
    "музыкальный жанр",
    "вид транспорта",
    "напиток",
    "предмет мебели",
    "персонаж мультфильма",
    "погода",
]


def _log(msg: str) -> None:
    """Force-log to stderr (bypasses gunicorn log config)."""
    sys.stderr.write(f"[wrapped] {msg}\n")
    sys.stderr.flush()


def _is_ru(lang_code: str | None) -> bool:
    return (lang_code or "ru") in ALMOST_CIS_LANGUAGES


async def _resolve_is_ru(user_id: int, tg_lang: str | None) -> bool:
    """Check user_language table: if Russian is among user's languages, use Russian.
    Russian is dominant — many CIS users browse memes in both ru and en."""
    try:
        langs = await get_user_languages(user_id)
        if langs:
            # If any CIS language is in user's bot language preferences → Russian
            if langs & set(ALMOST_CIS_LANGUAGES):
                return True
            return False
    except Exception:
        pass
    # Fallback to Telegram language
    return _is_ru(tg_lang)


def _loading_msg(is_ru: bool) -> str:
    return random.choice(LOADING_MESSAGES_RU if is_ru else LOADING_MESSAGES_EN)


def _loading_btn(is_ru: bool) -> str:
    return random.choice(LOADING_BUTTONS_RU if is_ru else LOADING_BUTTONS_EN)


def _next_label(is_ru: bool) -> str:
    return "Дальше →" if is_ru else "Next →"


# ── LLM ──────────────────────────────────────────────────


async def call_deepseek(prompt: str) -> str:
    client = AsyncOpenAI(
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
    )
    resp = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
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

    row = await fetch_one(
        text(
            """
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
    """
        ),
        {"user_id": user_id},
    )

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
    row = await fetch_one(
        text(
            f"""
        SELECT
            EXTRACT(HOUR FROM reacted_at + interval '{tz_offset} hours')
                AS peak_hour,
            COUNT(*) AS cnt
        FROM user_meme_reaction
        WHERE user_id = :user_id AND reacted_at IS NOT NULL
        GROUP BY 1 ORDER BY 2 DESC LIMIT 1
    """
        ),
        {"user_id": user_id},
    )

    if not row:
        return {}
    hour = int(row["peak_hour"])
    if is_ru:
        labels = {
            (0, 6): "ночной скроллер 🌙",
            (6, 10): "утренний мемолюб ☀️",
            (10, 14): "дневной прокрастинатор 💼",
            (14, 18): "послеобеденный залипатель 🍕",
            (18, 22): "вечерний мемоман 🌆",
            (22, 24): "полуночный скроллер 🦉",
        }
        default_label = "мемоман"
    else:
        labels = {
            (0, 6): "night scroller 🌙",
            (6, 10): "morning meme lover ☀️",
            (10, 14): "daytime procrastinator 💼",
            (14, 18): "afternoon meme addict 🍕",
            (18, 22): "evening meme connoisseur 🌆",
            (22, 24): "midnight scroller 🦉",
        }
        default_label = "meme lover"
    label = next(
        (v for (lo, hi), v in labels.items() if lo <= hour < hi),
        default_label,
    )
    tz_label = "МСК" if is_ru else "UTC"
    return {"hour": hour, "label": label, "tz": tz_label}


async def get_surprise_meme(user_id: int) -> dict | None:
    """Meme user liked but most others didn't."""
    from sqlalchemy import text

    from src.database import fetch_one

    row = await fetch_one(
        text(
            """
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
    """
        ),
        {"user_id": user_id},
    )
    if not row:
        return None
    return dict(row)


async def get_most_popular_liked_meme(user_id: int) -> dict | None:
    """Meme user liked with highest global like rate."""
    from sqlalchemy import text

    from src.database import fetch_one

    row = await fetch_one(
        text(
            """
        SELECT m.id AS meme_id, m.type, m.telegram_file_id,
               ROUND(COALESCE(ms.lr_smoothed, 0.5) * 100)
                   AS global_lr_pct,
               COALESCE(ms.nlikes, 0) AS nlikes
        FROM user_meme_reaction umr
        JOIN meme m ON m.id = umr.meme_id
        LEFT JOIN meme_stats ms ON ms.meme_id = m.id
        WHERE umr.user_id = :user_id
          AND umr.reaction_id = 1
          AND m.telegram_file_id IS NOT NULL
          AND COALESCE(ms.nmemes_sent, 0) >= 10
        ORDER BY ms.lr_smoothed DESC LIMIT 1
    """
        ),
        {"user_id": user_id},
    )
    if not row:
        return None
    return dict(row)


async def get_unpopular_opinion_meme(user_id: int) -> dict | None:
    """Meme user disliked but was very popular globally."""
    from sqlalchemy import text

    from src.database import fetch_one

    row = await fetch_one(
        text(
            """
        SELECT m.id AS meme_id, m.type, m.telegram_file_id,
               ROUND(COALESCE(ms.lr_smoothed, 0.5) * 100)
                   AS global_lr_pct,
               COALESCE(ms.nlikes, 0) AS nlikes
        FROM user_meme_reaction umr
        JOIN meme m ON m.id = umr.meme_id
        LEFT JOIN meme_stats ms ON ms.meme_id = m.id
        WHERE umr.user_id = :user_id
          AND umr.reaction_id = 2
          AND m.telegram_file_id IS NOT NULL
          AND COALESCE(ms.lr_smoothed, 0.5) > 0.65
          AND COALESCE(ms.nmemes_sent, 0) >= 10
        ORDER BY ms.lr_smoothed DESC LIMIT 1
    """
        ),
        {"user_id": user_id},
    )
    if not row:
        return None
    return dict(row)


# ── MAIN HANDLER ─────────────────────────────────────────


async def handle_wrapped(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    user_id = update.effective_user.id
    _log(f"handle_wrapped called for {user_id}")

    # Send typing immediately so user knows the bot is alive
    try:
        await context.bot.send_chat_action(chat_id=user_id, action=ChatAction.TYPING)
    except Exception:
        pass

    await create_or_update_user(id=user_id)
    await save_tg_user(
        id=user_id,
        username=update.effective_user.username,
        first_name=update.effective_user.first_name,
        last_name=update.effective_user.last_name,
        is_premium=update.effective_user.is_premium,
        language_code=update.effective_user.language_code,
    )

    user_lang = update.effective_user.language_code or "en"
    if not await check_if_user_follows_related_channel(
        context.bot,
        user_id,
        user_lang,
    ):
        channel_link = get_related_channel_link(user_lang)
        if user_lang in ALMOST_CIS_LANGUAGES:
            msg = (
                f"Статистика доступна только подписчикам нашего канала 😉\n\n"
                f"Подпишись:\n{channel_link}"
            )
        else:
            msg = (
                f"Stats are available for channel subscribers only 😉\n\n"
                f"Subscribe:\n{channel_link}"
            )
        return await update.message.reply_text(msg)

    is_ru = await _resolve_is_ru(user_id, user_lang)

    cached = await get_user_wrapped(user_id)
    if cached and not cached.get("lock"):
        return await handle_wrapped_button(update, context)
    if cached and cached.get("lock"):
        msg = (
            "⏳ Уже генерирую твой Wrapped... подожди пару секунд!"
            if is_ru
            else "⏳ Already generating your Wrapped... hold on!"
        )
        return await update.message.reply_text(msg)

    # Check conditions BEFORE showing welcome
    user_stats_data = await get_user_stats(user_id)
    if not user_stats_data:
        msg = (
            "Маловато ты пользовался ботом 😅 /start"
            if is_ru
            else "You haven't used the bot enough yet 😅 /start"
        )
        return await update.message.reply_text(msg)
    nmemes_sent = user_stats_data.get("nmemes_sent", 0)
    if nmemes_sent < WRAPPED_MIN_REACTIONS:
        remaining = WRAPPED_MIN_REACTIONS - nmemes_sent
        msg = (
            f"Посмотри ещё {remaining} мемов и возвращайся! /start"
            if is_ru
            else f"Check out {remaining} more memes and come back! /start"
        )
        return await update.message.reply_text(msg)
    descriptions = await get_meme_descriptions_for_wrapped(
        user_id,
        limit=40,
    )
    if len(descriptions) < WRAPPED_MIN_DESCRIPTIONS:
        msg = (
            "Мы ещё анализируем твои мемы... 🔬\nПопробуй через пару часов! /start"
            if is_ru
            else "We're still analyzing your memes... 🔬\nTry again in a couple of hours! /start"
        )
        return await update.message.reply_text(msg)

    # ── START DEEPSEEK EARLY (while user reads welcome) ──
    user = await get_user_by_id(user_id)
    is_ru = await _resolve_is_ru(user_id, user_lang)
    lang = "ru" if is_ru else "en"
    stats_report = await get_bot_usage_report(
        user_id,
        user_stats_data,
        user,
        is_ru,
    )
    asyncio.create_task(
        _generate_and_cache(
            user_id,
            descriptions,
            lang,
            stats_report or "",
            is_ru,
        )
    )

    # Welcome message
    if is_ru:
        welcome_text = (
            "🎁 Мы подготовили глубокий анализ твоего чувства юмора.\n\nХочешь посмотреть?"
        )
        welcome_btn = "ПОСМОТРЕТЬ 🔮"
    else:
        welcome_text = (
            "🎁 We've prepared a deep analysis of your sense of humor.\n\nWant to see it?"
        )
        welcome_btn = "LET'S GO 🔮"
    await update.effective_chat.send_message(
        text=welcome_text,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(welcome_btn, callback_data="wrapped_go")]]
        ),
    )


async def handle_wrapped_go(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """ДА / ПОСМОТРЕТЬ pressed — show stats slide."""
    if update.callback_query:
        await update.callback_query.answer()

    user_id = update.effective_user.id
    _log(f"handle_wrapped_go called for {user_id}")
    try:
        await context.bot.send_chat_action(
            chat_id=user_id,
            action=ChatAction.TYPING,
        )
    except Exception:
        pass

    cached = await get_user_wrapped(user_id)
    if cached and not cached.get("lock"):
        return await handle_wrapped_button(update, context)

    # Still generating — edit the button message with loading text
    is_ru = (
        cached.get("is_ru", _is_ru(update.effective_user.language_code))
        if cached
        else _is_ru(update.effective_user.language_code)
    )
    if cached and cached.get("lock"):
        stats = cached.get("stats_report")
        if stats and update.callback_query:
            try:
                await update.callback_query.message.edit_text(
                    text=stats,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton(_next_label(is_ru), callback_data="wrapped_1")]]
                    ),
                )
            except Exception:
                pass
            return
        # Still no stats — edit existing message
        if update.callback_query:
            try:
                await update.callback_query.message.edit_text(
                    text=_loading_msg(is_ru),
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton(_loading_btn(is_ru), callback_data="wrapped_1")]]
                    ),
                )
            except Exception:
                pass
        return

    # No cache at all — shouldn't happen, but handle gracefully
    msg = "Попробуй /wrapped ещё раз" if is_ru else "Try /wrapped again"
    await update.effective_chat.send_message(msg)


async def _generate_and_cache(
    user_id: int,
    descriptions: list,
    lang: str,
    stats_report: str,
    is_ru: bool = True,
):
    """Background: generate all data and save to cache."""
    try:
        # Save stats immediately so ДА can show them
        await set_user_wrapped(
            user_id,
            {"lock": True, "stats_report": stats_report, "is_ru": is_ru},
            ttl=300,
        )
        _log(f"starting generation for {user_id}")

        data = await generate_wrapped_data(
            user_id,
            descriptions,
            lang,
            stats_report,
        )
        if data:
            data["is_ru"] = is_ru
            await set_user_wrapped(user_id, data)
            _log(f"done for {user_id}")
        else:
            _log(f"returned None for {user_id}")
    except Exception as e:
        _log(f"bg error for {user_id}: {e}")
        from src.redis import redis_client

        await redis_client.delete(f"wrapped:{user_id}")


# ── SLIDE NAVIGATION ─────────────────────────────────────


async def handle_wrapped_button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    cb = update.callback_query.data if update.callback_query else "none"
    _log(f"handle_wrapped_button ENTRY cb={cb}")
    user_id = update.effective_user.id
    uw = await get_user_wrapped(user_id)
    if not uw:
        _log(f"no cache for {user_id}")
        return

    is_ru = uw.get("is_ru", _is_ru(update.effective_user.language_code))
    if uw.get("lock"):
        _log(f"lock active for {user_id}, editing message")
        if update.callback_query:
            await update.callback_query.answer()
            # EDIT existing message instead of sending new one
            try:
                await update.callback_query.message.edit_text(
                    text=_loading_msg(is_ru),
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    _loading_btn(is_ru), callback_data=update.callback_query.data
                                )
                            ]
                        ]
                    ),
                )
            except Exception:
                # edit_text fails if text is identical — ignore
                pass
        return

    if update.callback_query:
        await update.callback_query.answer()
        suffix = update.callback_query.data.replace("wrapped_", "")
        if suffix.isdigit():
            key = int(suffix)
        else:
            key = 0  # "wrapped_go" or any non-numeric → start from slide 0
    else:
        key = 0

    _log(f"user={user_id} key={key}")

    # Delete only the welcome/loading message (slide 0 transition)
    if update.callback_query and key == 0:
        try:
            await update.callback_query.message.delete()
        except Exception:
            pass

    try:
        await context.bot.send_chat_action(
            chat_id=user_id,
            action=ChatAction.TYPING,
        )
    except Exception:
        pass

    try:
        await _show_slide(update, context, uw, key, user_id)
    except Exception as e:
        logger.error(
            "[wrapped] slide %d error for %d: %s",
            key,
            user_id,
            e,
            exc_info=True,
        )
        # Try to send next slide as fallback
        try:
            if key < 9:
                await _show_slide(
                    update,
                    context,
                    uw,
                    key + 1,
                    user_id,
                )
        except Exception:
            pass


async def _show_slide(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    uw: dict,
    key: int,
    user_id: int,
) -> None:
    """Send a single slide. Extracted for error isolation."""
    ru = uw.get("is_ru", _is_ru(update.effective_user.language_code))

    # ── Slide 0: Stats ──
    if key == 0:
        txt = uw.get("stats_report") or "📊"
        await update.effective_chat.send_message(
            text=txt,
            parse_mode="HTML",
            reply_markup=_next_btn("wrapped_1", ru),
        )

    # ── Slide 1: Zodiac ──
    if key == 1:
        txt = uw.get("zodiac", "")
        if txt:
            try:
                await update.effective_chat.send_message(
                    text=txt,
                    parse_mode="HTML",
                    reply_markup=_next_btn("wrapped_2", ru),
                )
            except Exception as e:
                _log(f"zodiac slide error: {e}")
                key = 2
        else:
            key = 2

    # ── Slide 2: Your meme ──
    if key == 2:
        sent = False
        meme_info = uw.get("your_meme")
        try:
            if meme_info and meme_info.get("meme_id"):
                md = await get_meme_by_id(meme_info["meme_id"])
                if md and md.get("telegram_file_id"):
                    meme = MemeData(
                        id=md["id"],
                        type=md["type"],
                        telegram_file_id=md["telegram_file_id"],
                        caption=meme_info.get("caption", "🎯 Этот мем — это ты"),
                    )
                    await send_new_message_with_meme(
                        context.bot,
                        user_id,
                        meme,
                        reply_markup=_next_btn("wrapped_3", ru),
                    )
                    sent = True
        except Exception as e:
            _log(f"meme slide error: {e}")
        if not sent:
            key = 3

    # ── Slide 3: Humor DNA (bars only) ──
    if key == 3:
        txt = uw.get("humor_dna", "")
        if txt:
            try:
                await update.effective_chat.send_message(
                    text=txt,
                    parse_mode="HTML",
                    reply_markup=_next_btn("wrapped_4", ru),
                )
            except Exception as e:
                _log(f"humor dna error: {e}")
                key = 4
        else:
            key = 4

    # ── Slide 4: Humor oneliner + random liked meme ──
    if key == 4:
        oneliner = uw.get("humor_oneliner", "")
        meme_id = uw.get("oneliner_meme_id")
        sent = False
        if oneliner and meme_id:
            try:
                md = await get_meme_by_id(meme_id)
                if md and md.get("telegram_file_id"):
                    header = (
                        "👀 <b>Твой юмор одной фразой:</b>"
                        if ru
                        else "👀 <b>Your humor in one line:</b>"
                    )
                    caption = f"{header}\n\n<i>{html_escape(oneliner)}</i>"
                    meme = MemeData(
                        id=md["id"],
                        type=md["type"],
                        telegram_file_id=md["telegram_file_id"],
                        caption=caption,
                    )
                    await send_new_message_with_meme(
                        context.bot,
                        user_id,
                        meme,
                        reply_markup=_next_btn("wrapped_5", ru),
                    )
                    sent = True
            except Exception as e:
                _log(f"oneliner slide error: {e}")
        if not sent and oneliner:
            header = (
                "👀 <b>Твой юмор одной фразой:</b>" if ru else "👀 <b>Your humor in one line:</b>"
            )
            await update.effective_chat.send_message(
                text=f"{header}\n\n<i>{html_escape(oneliner)}</i>",
                parse_mode="HTML",
                reply_markup=_next_btn("wrapped_5", ru),
            )
        elif not sent:
            key = 5

    # ── Slide 5: Absurd comparisons (separate messages with memes) ──
    if key == 5:
        items = uw.get("absurd_items", [])
        sent = False
        for i, item in enumerate(items[:3]):
            is_last = i == len(items[:3]) - 1
            cat = html_escape(item.get("category", "?"))
            thing = html_escape(item.get("thing", "?"))
            why = html_escape(item.get("why", ""))
            if ru:
                caption = f"🎰 <b>Если бы ты был — {cat}:</b>\n\n<b>{thing}</b>\n<i>{why}</i>"
            else:
                caption = f"🎰 <b>If you were a {cat}:</b>\n\n<b>{thing}</b>\n<i>{why}</i>"
            mid = item.get("meme_id")
            markup = _next_btn("wrapped_6", ru) if is_last else None
            if mid:
                try:
                    md = await get_meme_by_id(mid)
                    if md and md.get("telegram_file_id"):
                        meme = MemeData(
                            id=md["id"],
                            type=md["type"],
                            telegram_file_id=md["telegram_file_id"],
                            caption=caption,
                        )
                        if sent:
                            await asyncio.sleep(5)
                        await send_new_message_with_meme(
                            context.bot,
                            user_id,
                            meme,
                            reply_markup=markup,
                        )
                        sent = True
                        continue
                except Exception as e:
                    _log(f"absurd meme error: {e}")
            # Fallback: text only
            try:
                if sent:
                    await asyncio.sleep(5)
                await update.effective_chat.send_message(
                    text=caption,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
                sent = True
            except Exception as e:
                _log(f"absurd text error: {e}")
        if not sent:
            key = 6

    # ── Slide 6: Anti-profile ──
    if key == 6:
        txt = uw.get("anti_profile", "")
        if txt:
            try:
                await update.effective_chat.send_message(
                    text=txt,
                    parse_mode="HTML",
                    reply_markup=_next_btn("wrapped_7", ru),
                )
            except Exception as e:
                _log(f"anti slide error: {e}")
                key = 7
        else:
            key = 7

    # ── Slide 7: Popular meme + unpopular opinion ──
    if key == 7:
        pop = uw.get("popular_meme")
        unpop = uw.get("unpopular_meme")
        sent = False
        for meme_data in [pop, unpop]:
            if meme_data and meme_data.get("meme_id"):
                try:
                    md = await get_meme_by_id(meme_data["meme_id"])
                    if md and md.get("telegram_file_id"):
                        meme = MemeData(
                            id=md["id"],
                            type=md["type"],
                            telegram_file_id=md["telegram_file_id"],
                            caption=meme_data["caption"],
                        )
                        await send_new_message_with_meme(
                            context.bot,
                            user_id,
                            meme,
                            reply_markup=_next_btn("wrapped_8", ru),
                        )
                        sent = True
                except Exception as e:
                    _log(f"meme stats error: {e}")
        if not sent:
            key = 8

    # ── Slide 8: Sources + speed + peak ──
    if key == 8:
        txt = uw.get("stats_extra", "")
        if txt:
            try:
                await update.effective_chat.send_message(
                    text=txt,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "Финалочка →" if ru else "The finale →",
                                    callback_data="wrapped_9",
                                )
                            ]
                        ]
                    ),
                )
            except Exception as e:
                _log(f"stats extra error: {e}")
                key = 9
        else:
            key = 9

    # ── Slide 9: Prediction + referral ──
    if key == 9:
        pred = uw.get("prediction", "")
        share_url = "https://t.me/ffmemesbot?start=wrapped"
        if ru:
            share_text = "Глубокий анализ чувства юмора 🔮"
            finale_text = (
                "🔮 <b>Предсказание на лето 2026:</b>\n\n"
                f"<i>{html_escape(pred)}</i>\n\n"
                "❤️ Спасибо за то, что пользуешься ботом.\n\n"
                "Перешли ссылку другу — пусть тоже узнает "
                "свой мем-профиль 👇"
            )
            share_btn = "📤 Отправить другу"
        else:
            share_text = "Deep analysis of your sense of humor 🔮"
            finale_text = (
                "🔮 <b>Prediction for summer 2026:</b>\n\n"
                f"<i>{html_escape(pred)}</i>\n\n"
                "❤️ Thanks for using the bot.\n\n"
                "Share the link with a friend — let them discover "
                "their meme profile too 👇"
            )
            share_btn = "📤 Share with a friend"
        share_link = f"https://t.me/share/url?url={quote(share_url)}&text={quote(share_text)}"
        await update.effective_chat.send_message(
            text=finale_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(share_btn, url=share_link)]]),
        )


def _next_btn(callback: str, is_ru: bool = True) -> InlineKeyboardMarkup:
    label = "Дальше →" if is_ru else "Next →"
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=callback)]])


async def handle_wrapped_clear(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
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
    user_id: int,
    descriptions: list,
    lang: str,
    stats_report: str,
) -> dict | None:
    # Lock is already set by _generate_and_cache (with is_ru), don't overwrite it

    try:
        liked = [d for d in descriptions if d.get("reaction_id") == 1]
        disliked = [d for d in descriptions if d.get("reaction_id") == 2]

        liked_texts = "\n".join(
            f"[{i}] ✅ {d.get('description') or d.get('ocr_text', '')}"
            for i, d in enumerate(liked[:25])
        )
        disliked_texts = "\n".join(
            f"❌ {d.get('description') or d.get('ocr_text', '')}" for d in disliked[:15]
        )

        # DeepSeek + SQL in parallel
        is_ru = _is_ru(lang)
        prompt = _build_mega_prompt(liked_texts, disliked_texts, lang)

        deepseek_task = asyncio.create_task(call_deepseek(prompt))
        sql_tasks = asyncio.gather(
            _safe(get_reaction_speed_insight(user_id)),
            _safe(get_peak_hour_insight(user_id, is_ru)),
            _safe(get_surprise_meme(user_id)),
            _safe(_build_sources_report(user_id, is_ru)),
            _safe(get_most_popular_liked_meme(user_id)),
            _safe(get_unpopular_opinion_meme(user_id)),
        )

        raw, (speed, peak, surprise, sources, popular_meme, unpopular_meme) = await asyncio.gather(
            deepseek_task, sql_tasks
        )

        p = parse_json_from_llm(raw)
        if not p:
            logger.warning(
                "DeepSeek JSON failed user %d: %s",
                user_id,
                raw[:300],
            )
            p = {}

        your_meme = _pick_meme(p, liked)

        # Use surprise meme if LLM didn't pick one
        if not your_meme and surprise:
            lr = surprise.get("global_lr_pct", "?")
            if is_ru:
                cap = f"🎲 Этот мем лайкнул только ты\n(глобальный лайк-рейт: {lr}%)"
            else:
                cap = f"🎲 Only you liked this meme\n(global like rate: {lr}%)"
            your_meme = {"meme_id": surprise["meme_id"], "caption": cap}
        if not your_meme and liked:
            pick = random.choice(liked[:10])
            cap = "🎲 А вот мем, который тебе зашёл:" if is_ru else "🎲 Here's a meme you liked:"
            your_meme = {"meme_id": pick["meme_id"], "caption": cap}

        # Build slides
        # Stats report gets vibe from DeepSeek — replace placeholder vibe
        vibe = p.get("vibe", "")
        if vibe and stats_report:
            if "\n<i>" in stats_report:
                idx = stats_report.rfind("\n<i>")
                stats_report = stats_report[:idx]
            stats_report += f"\n\n<i>{html_escape(vibe)}</i>"

        # Track used meme IDs globally to avoid showing the same meme twice
        global_used_memes = set()
        if your_meme and your_meme.get("meme_id"):
            global_used_memes.add(your_meme["meme_id"])

        # Pick oneliner meme (avoid your_meme)
        oneliner_meme_id = None
        if liked:
            oneliner_candidates = [m for m in liked[:10] if m["meme_id"] not in global_used_memes]
            if oneliner_candidates:
                oneliner_meme_id = random.choice(oneliner_candidates)["meme_id"]
            else:
                oneliner_meme_id = random.choice(liked[:10])["meme_id"]
            global_used_memes.add(oneliner_meme_id)

        # Pick memes for absurd comparisons (avoid already used)
        absurd_memes = _attach_memes_to_absurd(p, liked, global_used_memes)

        default_prediction = (
            "Летом ты будешь листать мемы вместо работы 🔥"
            if is_ru
            else "This summer you'll scroll memes instead of working 🔥"
        )
        return {
            "stats_report": stats_report,
            "zodiac": _build_zodiac_slide(p, is_ru),
            "your_meme": your_meme,
            "humor_dna": _build_humor_dna_slide(p, is_ru),
            "humor_oneliner": p.get("humor_oneliner", ""),
            "oneliner_meme_id": oneliner_meme_id,
            "absurd_items": absurd_memes,
            "anti_profile": _build_anti_slide(p, is_ru),
            "popular_meme": _build_meme_data(popular_meme, is_popular=True, is_ru=is_ru),
            "unpopular_meme": _build_meme_data(unpopular_meme, is_popular=False, is_ru=is_ru),
            "stats_extra": _build_extra_slide(sources, speed, peak, is_ru),
            "prediction": p.get("prediction", default_prediction),
        }
    except Exception as e:
        logger.error("Wrapped failed user %d: %s", user_id, e, exc_info=True)
        default_prediction = (
            "Летом ты будешь листать мемы вместо работы 🔥"
            if is_ru
            else "This summer you'll scroll memes instead of working 🔥"
        )
        return {
            "stats_report": stats_report,
            "zodiac": "",
            "your_meme": None,
            "humor_dna": "",
            "humor_oneliner": "",
            "oneliner_meme_id": None,
            "absurd_items": [],
            "anti_profile": "",
            "popular_meme": None,
            "unpopular_meme": None,
            "stats_extra": "",
            "prediction": default_prediction,
        }


async def _safe(coro):
    try:
        return await coro
    except Exception as e:
        logger.warning("Wrapped SQL insight failed: %s", e)
        return {} if not isinstance(e, TypeError) else None


def _build_mega_prompt(liked_texts: str, disliked_texts: str, lang: str = "ru") -> str:
    categories = random.sample(ABSURD_CATEGORIES, 3)

    lang_instruction = ""
    if lang != "ru":
        lang_name = "English" if lang == "en" else lang
        lang_instruction = f"\n- ЯЗЫК: пиши ВЕСЬ JSON на {lang_name}"

    return f"""Ты мем-психолог. Проанализируй чувство юмора.

ЛАЙКНУТЫЕ МЕМЫ:
{liked_texts}

СКИПНУТЫЕ МЕМЫ:
{disliked_texts}

Сначала молча найди:
1) 2-3 самые частые мотивы в лайках (офис, животные, кринж, токсичная мотивация, low-res chaos, семейная драма, etc.)
2) 1-2 мотива, которые человек стабильно скипает
3) 1 противоречие между лайками и скипами
Рассуждения НЕ выводи. Только JSON.

Верни ТОЛЬКО JSON:
{{
  "vibe": "подкол от друга по мемам, 10-15 слов",
  "meme_index": число (индекс лайкнутого мема [N], который олицетворяет),
  "meme_caption": "почему этот мем — это ты (2 предложения, подкол)",
  "zodiac_sign": "знак зодиака + эмодзи (♈♉♊♋♌♍♎♏♐♑♒♓)",
  "zodiac_why": "1-2 предложения. Выбирай знак НЕ по характеру, \
а по ЛОГИКЕ мемов. Упомяни конкретный мотив.",
  "humor_dna": [
    {{"name": "категория", "pct": число}},
    {{"name": "категория", "pct": число}},
    {{"name": "категория", "pct": число}},
    {{"name": "категория", "pct": число}},
    {{"name": "категория", "pct": число}}
  ],
  "humor_oneliner": "4-8 слов. Ярлык мем-вкуса, не комплимент. \
Как кличка от друга, не описание из гороскопа.",
  "anti_profile": "2-3 коротких абзаца через \\n\\n. \
На ТЫ: 'ты терпеть не можешь...'. Конкретно. \
Последний абзац ОБЯЗАТЕЛЬНО позитивный — что в этом крутого, \
почему такой вкус в мемах это кайф.",
  "absurd_comparisons": [
    {{"category": "{categories[0]}", "thing": "конкретный предмет", \
"why": "потому что ты лайкаешь X и Y — 1 предложение", \
"meme_ref": число}},
    {{"category": "{categories[1]}", "thing": "конкретный предмет", \
"why": "1 предложение", "meme_ref": число}},
    {{"category": "{categories[2]}", "thing": "конкретный предмет", \
"why": "1 предложение", "meme_ref": число}}
  ],
  "prediction": "конкретное абсурдное событие на лето 2026. 1-2 предложения."
}}

Правила:
- humor_dna: 5 конкретных прикольных категорий по 2-3 слова, проценты ~100
- zodiac: знак как метафора мемного поведения, не "кто он по жизни". \
ВАЖНО: НЕ БЛИЗНЕЦЫ. Близнецы — запрещённый знак. Выбирай из остальных 11 знаков. \
Привязывай знак к КОНКРЕТНЫМ паттернам в мемах (например: Овен если агрессивный юмор, \
Рыбы если меланхолия, Лев если самоирония, Козерог если сухой юмор, и т.д.)
- absurd_comparisons: thing = конкретный предмет (не "хаос-машина"). \
Каждый comparison на ДРУГИХ мотивах, не повторяй шутку. \
meme_ref ДОЛЖЕН быть РАЗНЫМ для каждого comparison (три разных числа!)
- meme_ref: индекс [N] из ЛАЙКНУТЫХ мемов. Каждый meme_ref уникален!
- meme_index: ДОЛЖЕН отличаться от всех meme_ref в absurd_comparisons

АНТИСЛОП:
- ЗАПРЕЩЕНЫ слова: уникальный, особенный, тонкий, изысканный, многогранный, хаотичный, вайб, ирония, абсурд (без конкретики)
- ЗАПРЕЩЕНЫ шаблоны: "ты из тех, кто...", "генерал постиронии", "ценитель абсурда"
- Подкалывай дружески, но ВСЕГДА заканчивай на позитивной ноте. \
Человек должен улыбнуться, а не расстроиться. \
Формула: подкол + комплимент ("ты залипаешь на X — но это потому что у тебя Y"). \
Если мемы пользователя про грусть, депрессию, одиночество — будь мягче и теплее. \
Не подчёркивай негатив, а покажи что юмор помогает справляться
- Каждое утверждение ДОЛЖНО опираться на конкретный мем
- Если шутка подошла бы любому — перепиши
- Лучший юмор = противоречия: "лайкаешь X, но скипаешь Y"{lang_instruction}"""


def _pick_meme(p: dict, liked: list) -> dict | None:
    idx = p.get("meme_index")
    cap = p.get("meme_caption", "🎯 Этот мем олицетворяет тебя")
    if idx is not None and 0 <= idx < len(liked):
        return {
            "meme_id": liked[idx]["meme_id"],
            "caption": f"🎯 Этот мем олицетворяет тебя:\n\n<i>{html_escape(cap)}</i>",
        }
    return None


def _build_humor_dna_slide(p: dict, is_ru: bool = True) -> str:
    """Humor DNA bars only — no roast text."""
    dna = p.get("humor_dna", [])

    def bar(pct):
        f = round(pct / 10)
        return "█" * f + "░" * (10 - f)

    header = "🧬 <b>Твоя ДНК юмора:</b>" if is_ru else "🧬 <b>Your Humor DNA:</b>"
    lines = [header + "\n"]
    for c in dna[:5]:
        pct = min(100, max(0, c.get("pct", 33)))
        lines.append(f"{bar(pct)} {pct}%\n{html_escape(c.get('name', '???'))}\n")

    return "\n".join(lines) if len(lines) > 1 else ""


def _build_zodiac_slide(p: dict, is_ru: bool = True) -> str:
    sign = p.get("zodiac_sign", "")
    why = p.get("zodiac_why", "")
    if not sign:
        return ""
    header = "🔮 <b>Твой мем-зодиак:</b>" if is_ru else "🔮 <b>Your Meme Zodiac:</b>"
    return f"{header}\n\n" f"<b>{html_escape(sign)}</b>\n\n" f"<i>{html_escape(why)}</i>"


def _attach_memes_to_absurd(p: dict, liked: list, used_ids: set | None = None) -> list:
    """Attach meme IDs to each absurd comparison, ensuring no duplicates."""
    comparisons = p.get("absurd_comparisons", [])
    result = []
    if used_ids is None:
        used_ids = set()
    else:
        used_ids = set(used_ids)  # don't mutate caller's set
    for c in comparisons[:3]:
        meme_id = None
        # Try LLM-suggested meme_ref (but skip if already used)
        ref = c.get("meme_ref")
        if ref is not None and isinstance(ref, int) and 0 <= ref < len(liked):
            candidate = liked[ref]["meme_id"]
            if candidate not in used_ids:
                meme_id = candidate
        # Fallback: random liked meme not yet used
        if not meme_id and liked:
            available = [m for m in liked[:15] if m["meme_id"] not in used_ids]
            if available:
                pick = random.choice(available)
                meme_id = pick["meme_id"]
        if meme_id:
            used_ids.add(meme_id)
        result.append(
            {
                "category": c.get("category", "?"),
                "thing": c.get("thing", "?"),
                "why": c.get("why", ""),
                "meme_id": meme_id,
            }
        )
    return result


def _build_meme_data(meme: dict | None, is_popular: bool, is_ru: bool = True) -> dict | None:
    if not meme:
        return None
    lr = meme.get("global_lr_pct", "?")
    nlikes = meme.get("nlikes")
    if is_popular:
        if is_ru:
            extra = f" ({nlikes} чел.)" if nlikes else ""
            caption = f"🏆 Самый залайканный мем из твоих лайков!\n\nЕго лайкнули {lr}%{extra}"
        else:
            extra = f" ({nlikes} people)" if nlikes else ""
            caption = f"🏆 The most liked meme from your likes!\n\nLiked by {lr}%{extra}"
    else:
        if is_ru:
            extra = f" ({nlikes} чел.)" if nlikes else ""
            caption = f"🤔 А этот мем ты скипнул...\n\nХотя его лайкнули {lr}%{extra}!"
        else:
            extra = f" ({nlikes} people)" if nlikes else ""
            caption = f"🤔 You skipped this one...\n\nBut {lr}%{extra} liked it!"
    return {"meme_id": meme["meme_id"], "caption": caption}


def _build_anti_slide(p: dict, is_ru: bool = True) -> str:
    anti = p.get("anti_profile", "")
    if not anti:
        return ""
    header = (
        "🚫 <b>Что говорят твои скипы:</b>" if is_ru else "🚫 <b>What your skips say about you:</b>"
    )
    return f"{header}\n\n{html_escape(anti)}"


def _build_extra_slide(
    sources: str,
    speed: dict,
    peak: dict,
    is_ru: bool = True,
) -> str:
    parts = []
    if sources:
        parts.append(sources)

    if speed:
        med = speed.get("median_sec", 0)
        ml = speed.get("median_like", 0)
        md = speed.get("median_dislike", 0)
        if is_ru:
            parts.append(
                f"⚡ <b>Скорость реакции:</b> {med} сек\n"
                f"(до лайка: {ml} сек, до скипа: {md} сек)"
            )
        else:
            parts.append(f"⚡ <b>Reaction speed:</b> {med}s\n" f"(to like: {ml}s, to skip: {md}s)")

    if peak:
        h = peak.get("hour", 0)
        label = peak.get("label", "")
        tz = peak.get("tz", "")
        if is_ru:
            parts.append(f"🕐 <b>Пик активности:</b> {h}:00 {tz}\nТы — {label}")
        else:
            parts.append(f"🕐 <b>Peak activity:</b> {h}:00 {tz}\nYou're a {label}")

    return "\n\n".join(parts) if parts else ""


async def _build_sources_report(user_id: int, is_ru: bool = True) -> str:
    sources = await get_most_liked_meme_source_urls(user_id, limit=10)
    real = [
        s
        for s in (sources or [])
        if s.get("url")
        and not s["url"].startswith("tg://user")
        and ("t.me/" in s["url"] or "vk.com/" in s["url"])
    ]
    if len(real) < 3:
        try:
            top = await get_top_meme_source_urls(limit=5)
            for t in top or []:
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
    header = "📡 <b>Твои топ мем-паблики:</b>" if is_ru else "📡 <b>Your top meme channels:</b>"
    return f"{header}\n\n{src_list}"


# ── STATS SLIDE ──────────────────────────────────────────


async def get_bot_usage_report(
    user_id: int,
    user_stats: dict,
    user: dict,
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

    if is_ru:
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
        if like_rate > 50:
            vibe = "Лайкаешь больше половины — тебе всё смешно 😄"
        elif like_rate > 30:
            vibe = "Лайкаешь каждый третий — у тебя есть вкус 👌"
        elif like_rate > 15:
            vibe = "Лайкаешь каждый пятый — избирательный 🧐"
        else:
            vibe = "Менее 15% мемов достойны — мем-сноб 🎩"
    else:
        report = (
            "📊 <b>Meme Wrapped 2026</b>\n\n"
            "Let's start with the numbers.\n\n"
            f"You've been with us for <b>{days}</b> days.\n\n"
            f"🤝 Seen <b>{memes_sent}</b> memes\n"
            f"👍 Liked <b>{likes}</b> of them "
            f"(<b>{like_rate}%</b>)\n"
            f"👋 Visited <b>{sessions}</b> times\n"
        )
        if time_sec > 0:
            if time_sec < 60:
                t = f"{time_sec}s"
            elif time_sec < 3600:
                t = f"{time_sec // 60}m {time_sec % 60}s"
            else:
                t = f"over {time_sec // 3600} hours 😳"
            report += f"🕒 Time in bot: <b>{t}</b>\n"
        if like_rate > 50:
            vibe = "You like more than half — everything's funny to you 😄"
        elif like_rate > 30:
            vibe = "You like every third one — you've got taste 👌"
        elif like_rate > 15:
            vibe = "You like every fifth one — picky 🧐"
        else:
            vibe = "Less than 15% are worthy — meme snob 🎩"

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
