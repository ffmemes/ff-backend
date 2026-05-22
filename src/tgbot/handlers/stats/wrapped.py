import asyncio
import datetime
import logging
import random
import sys
from html import escape as html_escape
from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from src.localizer import ALMOST_CIS_LANGUAGES
from src.redis import get_user_wrapped, set_user_wrapped
from src.stats.service import (
    get_meme_descriptions_for_wrapped,
    get_user_stats,
)
from src.storage.schemas import MemeData
from src.tgbot.handlers.stats.wrapped_generation import (
    generate_wrapped_data,
    get_bot_usage_report,
)
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
                f"Stats are available for channel subscribers only 😉\n\nSubscribe:\n{channel_link}"
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
