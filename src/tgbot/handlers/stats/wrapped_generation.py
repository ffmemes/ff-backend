import asyncio
import datetime
import json
import logging
import random
from html import escape as html_escape

from openai import AsyncOpenAI

from src.config import settings
from src.localizer import ALMOST_CIS_LANGUAGES
from src.stats.service import (
    get_most_liked_meme_source_urls,
    get_top_meme_source_urls,
)

logger = logging.getLogger(__name__)


def _is_ru(lang_code: str | None) -> bool:
    return (lang_code or "ru") in ALMOST_CIS_LANGUAGES


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
1) 2-3 самые частые мотивы в лайках (офис, животные, кринж,
токсичная мотивация, low-res chaos, семейная драма, etc.)
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
- ЗАПРЕЩЕНЫ слова: уникальный, особенный, тонкий, изысканный,
многогранный, хаотичный, вайб, ирония, абсурд (без конкретики)
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
    return f"{header}\n\n<b>{html_escape(sign)}</b>\n\n<i>{html_escape(why)}</i>"


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
                f"⚡ <b>Скорость реакции:</b> {med} сек\n(до лайка: {ml} сек, до скипа: {md} сек)"
            )
        else:
            parts.append(f"⚡ <b>Reaction speed:</b> {med}s\n(to like: {ml}s, to skip: {md}s)")

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
