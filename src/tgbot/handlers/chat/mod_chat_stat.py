"""Reply with short meme stats when a moderator forwards a bot meme to the mod chat."""

import logging
import re

from sqlalchemy import text
from telegram import Message
from telegram.constants import MessageEntityType

from src.database import fetch_one
from src.tgbot.constants import TELEGRAM_MODERATOR_CHAT_ID

logger = logging.getLogger(__name__)

# Bot meme deep link embedded in the caption HTML:
# https://t.me/ffmemesbot?start=m_<user_id>_<meme_id>
_MEME_DEEP_LINK_RE = re.compile(r"t\.me/ffmemesbot\?start=(?:m|s)_\d+_(\d+)", re.IGNORECASE)


async def handle_mod_chat_meme_forward(msg: Message) -> bool:
    """If this is a meme forward in the moderator chat, reply with short stats.

    Returns True when a reply was sent (caller should skip further handling).
    """
    if msg.chat.id != TELEGRAM_MODERATOR_CHAT_ID:
        return False
    if msg.forward_origin is None:
        return False

    meme_id = _extract_meme_id(msg)
    if meme_id is None:
        return False

    reply = await _build_stat_reply(meme_id)
    if not reply:
        return False

    try:
        await msg.reply_text(reply, disable_web_page_preview=True)
    except Exception as e:
        logger.error("mod-chat stat reply failed for meme %s: %s", meme_id, e, exc_info=True)
    return True


def _extract_meme_id(msg: Message) -> int | None:
    # Bot-sent memes embed the deep link inside a TEXT_LINK entity, so the URL
    # is not present in the plain caption text; iterate entities first.
    for ent in msg.caption_entities or msg.entities or []:
        if ent.type == MessageEntityType.TEXT_LINK and ent.url:
            m = _MEME_DEEP_LINK_RE.search(ent.url)
            if m:
                return int(m.group(1))
    # Fallback: literal URL in text/caption.
    body = msg.text or msg.caption or ""
    m = _MEME_DEEP_LINK_RE.search(body)
    return int(m.group(1)) if m else None


_STATS_QUERY = text(
    r"""
    SELECT
        m.id,
        COALESCE(rc.views, 0)        AS views,
        COALESCE(rc.nlikes, 0)       AS nlikes,
        COALESCE(rc.ndislikes, 0)    AS ndislikes,
        COALESCE(ms.sec_to_react, 0) AS sec_to_react,
        CASE
            WHEN msrc.type = 'telegram' AND mrt.post_id IS NOT NULL
                THEN msrc.url || '/' || mrt.post_id
            WHEN msrc.type = 'vk' AND mrv.url IS NOT NULL
                THEN mrv.url
            ELSE msrc.url
        END AS source_url,
        (
            SELECT count(*) FROM user_deep_link_log
            WHERE deep_link LIKE :mid_pattern OR deep_link LIKE :legacy_mid_pattern
        ) AS clicks
    FROM meme m
    LEFT JOIN (
        SELECT
            meme_id,
            COUNT(*)                              AS views,
            COUNT(*) FILTER (WHERE reaction_id=1) AS nlikes,
            COUNT(*) FILTER (WHERE reaction_id=2) AS ndislikes
        FROM user_meme_reaction
        WHERE meme_id = :mid
        GROUP BY meme_id
    ) rc ON rc.meme_id = m.id
    LEFT JOIN meme_stats ms       ON ms.meme_id = m.id
    LEFT JOIN meme_source msrc    ON msrc.id = m.meme_source_id
    LEFT JOIN meme_raw_telegram mrt
        ON msrc.type = 'telegram' AND mrt.id = m.raw_meme_id
    LEFT JOIN meme_raw_vk mrv
        ON msrc.type = 'vk' AND mrv.id = m.raw_meme_id
    WHERE m.id = :mid
    """
)


async def _build_stat_reply(meme_id: int) -> str | None:
    row = await fetch_one(
        _STATS_QUERY,
        {
            "mid": meme_id,
            "mid_pattern": rf"m\_%\_{meme_id}",
            "legacy_mid_pattern": rf"s\_%\_{meme_id}",
        },
    )
    if not row:
        return None

    views = row["views"] or 0
    nlikes = row["nlikes"] or 0
    ndislikes = row["ndislikes"] or 0
    sec = row["sec_to_react"] or 0
    clicks = row["clicks"] or 0
    source_url = row["source_url"]

    parts = [f"👁 {_fmt_k(views)}", f"👍 {nlikes}", f"👎 {ndislikes}"]
    # sec_to_react has a 99999 sentinel for "no data".
    if 0 < sec < 99999:
        parts.append(f"⏱ {sec:.1f}s")
    lines = [" · ".join(parts)]
    if clicks:
        lines.append(f"🔗 {clicks} click{'s' if clicks != 1 else ''}")
    if source_url:
        lines.append(f"src: {source_url}")
    return "\n".join(lines)


def _fmt_k(n: int) -> str:
    if n >= 10000:
        return f"{n / 1000:.1f}k"
    return str(n)
