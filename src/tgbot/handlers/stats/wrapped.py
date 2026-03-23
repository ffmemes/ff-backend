import datetime
import json
import logging

from openai import AsyncOpenAI
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from src.config import settings
from src.redis import get_user_wrapped, set_user_wrapped
from src.stats.service import (
    get_meme_descriptions_for_wrapped,
    get_user_stats,
)
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

logger = logging.getLogger(__name__)

WRAPPED_MIN_REACTIONS = 30
WRAPPED_MIN_DESCRIPTIONS = 5


async def call_chatgpt(prompt: str) -> str:
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    response = await client.chat.completions.create(
        model="gpt-4.1",
        messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        max_tokens=500,
    )
    return response.choices[0].message.content


async def call_chatgpt_json(prompt: str) -> dict | None:
    """Call ChatGPT and parse JSON response. Returns None on failure."""
    try:
        raw = await call_chatgpt(prompt)
        # Strip markdown fences if present
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
    """Determine user's preferred language for the Wrapped report.

    Priority: Telegram language_code, preferring 'ru' if available.
    """
    lang = user.get("language_code") if user else None
    return lang if lang else "ru"


def is_wrapped_event_active() -> bool:
    """Check if Wrapped is currently available."""
    now = datetime.datetime.utcnow()
    # After April 7: command-only (always available via command)
    return True


async def is_wrapped_auto_trigger_active(user_id: int) -> bool:
    """Check if auto-trigger at 30th meme is active."""
    now = datetime.datetime.utcnow()
    # Before April 1: moderators only
    if now < datetime.datetime(2026, 4, 1):
        user = await get_user_by_id(user_id)
        return user and user.get("type") in ("moderator", "admin")
    # April 1-7: all users
    if now <= datetime.datetime(2026, 4, 7):
        return True
    # After April 7: auto-trigger disabled
    return False


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

    # Channel subscription gate
    if not await check_if_user_chat_member(
        context.bot,
        user_id,
        TELEGRAM_CHANNEL_RU_CHAT_ID,
    ):
        return await update.message.reply_text(
            f"Статистика доступна только подписчикам нашего канала 😉\n\n"
            f"Подпишись:\n{TELEGRAM_CHANNEL_RU_LINK}"
        )

    # Check cache
    user_wrapped = await get_user_wrapped(user_id)
    if user_wrapped and not user_wrapped.get("lock"):
        return await handle_wrapped_button(update, context)

    if user_wrapped and user_wrapped.get("lock"):
        return  # generation in progress

    # Check minimum reactions
    user_stats_data = await get_user_stats(user_id)
    if not user_stats_data:
        return await update.message.reply_text(
            "Маловато ты пользовался ботом 😅\n\n"
            "Посмотри побольше мемов и возвращайся! /start"
        )

    nmemes_sent = user_stats_data.get("nmemes_sent", 0)
    if nmemes_sent < WRAPPED_MIN_REACTIONS:
        remaining = WRAPPED_MIN_REACTIONS - nmemes_sent
        return await update.message.reply_text(
            f"Посмотри ещё {remaining} мемов, чтобы получить свой Wrapped 🎁\n\n"
            f"Жми /start и листай!"
        )

    # Check OCR/description coverage
    descriptions = await get_meme_descriptions_for_wrapped(user_id, limit=30)
    if len(descriptions) < WRAPPED_MIN_DESCRIPTIONS:
        return await update.message.reply_text(
            "Мы ещё анализируем твои мемы... 🔬\n\n"
            "Попробуй через пару часов! А пока — /start"
        )

    # Show stats slide immediately, then generate LLM content in background
    user = await get_user_by_id(user_id)
    lang = get_user_interface_language(user)
    is_ru = lang == "ru"

    bot_usage_report = await get_bot_usage_report(user_id, is_ru)
    if bot_usage_report is None:
        return await update.message.reply_text(
            "Маловато данных 😅 Жми /start" if is_ru
            else "Not enough data 😅 Press /start"
        )

    # Send stats slide right away (user sees it while LLM works)
    await update.effective_chat.send_message(
        text=bot_usage_report,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(
                "Дальше →" if is_ru else "Next →",
                callback_data="wrapped_1",
            )]]
        ),
    )

    # Generate LLM content in background
    user_wrapped = await generate_user_wrapped(
        user_id, update, descriptions, is_ru, bot_usage_report,
    )
    if user_wrapped is None:
        return
    await set_user_wrapped(user_id, user_wrapped)


async def handle_wrapped_button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    user_wrapped = await get_user_wrapped(update.effective_user.id)
    if not user_wrapped:
        return

    # Race condition guard: user pressed "Next" before LLM finished
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

    if key == 0:
        # Slide 1: Stats
        await update.effective_chat.send_message(
            text=user_wrapped["bot_usage_report"],
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Дальше →", callback_data="wrapped_1")]]
            ),
        )
    if key == 1:
        # Slide 2: "This meme represents you"
        your_meme = user_wrapped.get("your_meme_report")
        if your_meme and your_meme.get("meme_id"):
            meme_data = await get_meme_by_id(your_meme["meme_id"])
            if meme_data:
                meme = MemeData(**meme_data)
                caption = f"🎯 Этот мем — это ты:\n\n\"{your_meme.get('reason', '')}\""
                if meme_data.get("caption"):
                    caption += "\n\n" + meme_data["caption"]
                await send_new_message_with_meme(
                    context.bot,
                    update.effective_user.id,
                    meme,
                    caption=caption,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("Дальше →", callback_data="wrapped_2")]]
                    ),
                )
            else:
                key = 2  # skip to humor DNA
        else:
            key = 2

    if key == 2:
        # Slide 3: Humor DNA
        humor_report = user_wrapped.get("humor_dna_report", "")
        if humor_report:
            await update.effective_chat.send_message(
                text=humor_report,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Финалочка →", callback_data="wrapped_3")]]
                ),
            )
        else:
            key = 3

    if key == 3:
        # Slide 4: Final + prediction
        prediction = user_wrapped.get("prediction", "")
        text_msg = (
            "🔮 Предсказание на лето 2026:\n\n"
            f"<i>{prediction}</i>\n\n"
            "❤️ Спасибо за то, что пользуешься ботом!\n"
            "Продолжай смотреть мемы и пересылать их друзьям.\n\n"
            "@ffmemesbot 🍔\n\n"
            "/start"
        )
        await update.effective_chat.send_message(
            text=text_msg,
            parse_mode="HTML",
        )


async def handle_wrapped_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to clear Wrapped cache for testing."""
    user_id = update.effective_user.id
    user = await get_user_by_id(user_id)
    if not user or user.get("type") not in ("moderator", "admin"):
        return

    from src.redis import redis_client
    key = f"wrapped:{user_id}"
    await redis_client.delete(key)
    await update.message.reply_text("Wrapped cache cleared. Try /wrapped again.")


async def generate_user_wrapped(
    user_id: int,
    update: Update,
    descriptions: list,
    is_ru: bool = True,
    bot_usage_report: str = "",
):
    """Generate LLM content for Wrapped. Stats slide already sent."""
    await set_user_wrapped(user_id, {"lock": True}, ttl=300)  # 5 min TTL

    try:
        # LLM calls (user is reading stats slide while these run)
        your_meme_report = await get_your_meme_report(descriptions, is_ru)
        humor_dna_report = await get_humor_dna_report(descriptions, is_ru)
        prediction = await get_prediction(descriptions, is_ru)

        return {
            "bot_usage_report": bot_usage_report,
            "your_meme_report": your_meme_report,
            "humor_dna_report": humor_dna_report,
            "prediction": prediction,
        }
    except Exception as e:
        logger.error(
            "Error generating wrapped for user %d: %s",
            user_id, e, exc_info=True,
        )
        # Still return partial data so user gets something
        return {
            "bot_usage_report": bot_usage_report,
            "your_meme_report": {},
            "humor_dna_report": "",
            "prediction": (
                "Лето будет мемным! 🔥" if is_ru
                else "Your summer will be full of memes! 🔥"
            ),
        }


async def get_bot_usage_report(user_id: int, is_ru: bool = True):
    user = await get_user_by_id(user_id)
    user_stats = await get_user_stats(user_id)
    if user_stats is None:
        return None

    days_with_us = (datetime.datetime.utcnow() - user["created_at"]).days + 1
    sessions = user_stats.get("nsessions", 0)
    memes_sent = user_stats.get("nmemes_sent", 0)
    likes = user_stats.get("nlikes", 0)
    time_sec = user_stats.get("time_spent_sec", 0)

    if likes < 10:
        return None

    # Make stats fun, not dry
    like_rate = round(100 * likes / max(memes_sent, 1))

    if is_ru:
        # Fun commentary based on stats
        if like_rate > 60:
            vibe = "Ты — мем-оптимист. Лайкаешь всё подряд 😄"
        elif like_rate > 40:
            vibe = "У тебя здоровый вкус — лайкаешь ровно то, что смешно 👌"
        elif like_rate > 20:
            vibe = "Ты — мем-критик. Только избранные мемы заслуживают твой лайк 🧐"
        else:
            vibe = "Ты — мем-сноб. Менее 20% мемов достойны. Уважаю 🎩"

        report = (
            f"📊 <b>Meme Wrapped 2026</b>\n\n"
            f"Ты с нами уже <b>{days_with_us}</b> дней.\n\n"
            f"🤝 Ты посмотрел <b>{memes_sent}</b> мемов\n"
            f"👍 Лайкнул <b>{likes}</b> из них "
            f"(<b>{like_rate}%</b>)\n"
            f"👋 Заходил <b>{sessions}</b> раз\n"
        )
    else:
        if like_rate > 60:
            vibe = "You're a meme optimist — like everything! 😄"
        elif like_rate > 40:
            vibe = "You have great taste — like what's actually funny 👌"
        elif like_rate > 20:
            vibe = "You're a meme critic — only the best get your like 🧐"
        else:
            vibe = "You're a meme snob — less than 20% worthy. Respect 🎩"

        report = (
            f"📊 <b>Meme Wrapped 2026</b>\n\n"
            f"You've been with us for <b>{days_with_us}</b> days.\n\n"
            f"🤝 You've seen <b>{memes_sent}</b> memes\n"
            f"👍 Liked <b>{likes}</b> of them "
            f"(<b>{like_rate}%</b>)\n"
            f"👋 Opened the bot <b>{sessions}</b> times\n"
        )

    if time_sec > 0:
        if time_sec < 60:
            time_str = f"{time_sec} сек" if is_ru else f"{time_sec} sec"
        elif time_sec < 3600:
            m, s = time_sec // 60, time_sec % 60
            time_str = f"{m} мин {s} сек" if is_ru else f"{m} min {s} sec"
        else:
            h = time_sec // 3600
            time_str = (
                f"больше {h} часов 😳"
                if is_ru else f"over {h} hours 😳"
            )
        report += (
            f"🕒 {'Провёл в боте' if is_ru else 'Spent'} "
            f"<b>{time_str}</b>\n"
        )

    report += f"\n<i>{vibe}</i>"

    return report


async def get_your_meme_report(descriptions: list, is_ru: bool = True) -> dict:
    """Use LLM to pick the meme that best represents the user."""
    liked = [d for d in descriptions if d["reaction_id"] == 1 and d.get("description")]
    if not liked:
        return {}

    meme_texts = "\n".join(
        f"[{i}] {d['description']}" for i, d in enumerate(liked[:20])
    )

    lang_instruction = "Ответь на русском языке." if is_ru else "Answer in English."

    prompt = f"""You're a witty friend analyzing someone's meme taste. \
Here are memes they liked:

{meme_texts}

Pick the ONE meme that IS this person. Not the funniest — the one \
that reveals something true about their personality or worldview.

Return JSON: {{"meme_index": N, "reason": "..."}}

The reason must be:
- Written as if you're roasting a friend at a party
- Reference the SPECIFIC meme content (not vague)
- Reveal something about the person (not the meme)
- Max 2 sentences, punchy
{lang_instruction}"""

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


async def get_humor_dna_report(descriptions: list, is_ru: bool = True) -> str:
    """Use LLM to generate humor DNA categories with emoji bars."""
    desc_texts = "\n".join(
        f"[{'liked' if d['reaction_id'] == 1 else 'disliked'}] "
        f"{d.get('description', d.get('ocr_text', ''))}"
        for d in descriptions[:30]
    )

    if is_ru:
        lang_instruction = "Названия категорий и summary на русском."
    else:
        lang_instruction = "Category names and summary in English."

    prompt = f"""You're a humor psychologist diagnosing someone's meme DNA.

Memes they LIKED (✓) and DISLIKED (✗):
{desc_texts}

Return JSON with EXACTLY 3 humor categories:
{{"categories": [{{"name": "...", "pct": N}}, ...], \
"summary": "..."}}

Rules for categories:
- Must be SPECIFIC and FUNNY names (not "Funny" or "Relatable")
- Each name max 2-3 words
- Percentages roughly sum to 100
- Summary: one roast-style sentence about their overall humor
- Pay attention to what they DISLIKED — it reveals as much

{lang_instruction}
Good names: "Абсурд", "Жиза", "Депрессивный позитив", \
"Токсичная ностальгия", "Офисный ад", "Кринж как искусство"
Bad names: "Юмор", "Мемы", "Смешное", "Разное\""""

    result = await call_chatgpt_json(prompt)
    if not result or "categories" not in result:
        return ""

    categories = result["categories"]
    summary = result.get("summary", "")

    def make_bar(pct: int) -> str:
        filled = round(pct / 10)
        return "█" * filled + "░" * (10 - filled)

    lines = ["🧬 <b>Твоя ДНК юмора:</b>\n" if is_ru else "🧬 <b>Your Humor DNA:</b>\n"]
    for cat in categories[:3]:
        pct = min(100, max(0, cat.get("pct", 50)))
        bar = make_bar(pct)
        lines.append(f"{bar} {pct}% {cat.get('name', '???')}")

    if summary:
        lines.append(f"\n{summary}")

    return "\n".join(lines)


async def get_prediction(descriptions: list, is_ru: bool = True) -> str:
    """Use LLM to generate a fun summer prediction."""
    desc_sample = "\n".join(
        d.get("description", d.get("ocr_text", ""))
        for d in descriptions[:10]
        if d.get("description") or d.get("ocr_text")
    )

    lang_instruction = "Ответь на русском языке." if is_ru else "Answer in English."

    prompt = f"""Based on these meme preferences:

{desc_sample}

Generate a SPECIFIC and ABSURD prediction for this person's summer 2026.

Rules:
- Must reference their actual meme taste (not generic)
- Must be funny enough to screenshot and send to a friend
- One prediction, 1-2 sentences max
- Be bold and weird — this is entertainment, not a horoscope
{lang_instruction}"""

    try:
        return await call_chatgpt(prompt)
    except Exception:
        return "Лето будет мемным! 🔥" if is_ru else "Your summer will be full of memes! 🔥"
