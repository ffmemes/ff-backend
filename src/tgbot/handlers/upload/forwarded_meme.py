from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

BOT_DEEP_LINK_REGEXP = re.compile(r"s_\d+_\d+")
MEME_ID_REGEXP = re.compile(r"s_\d+_(\d+)")
URL_REGEXP = re.compile(r"https?://\S+")


def was_forwarded_from_bot(message: Any, bot_id: int) -> bool:
    if message is None:
        return False

    forward_from = getattr(message, "forward_from", None)
    if forward_from and getattr(forward_from, "id", None) == bot_id:
        return True

    forward_origin = getattr(message, "forward_origin", None)
    sender_user = getattr(forward_origin, "sender_user", None) if forward_origin else None
    if sender_user and getattr(sender_user, "id", None) == bot_id:
        return True

    return False


def _iter_message_urls(message: Any) -> Iterable[str]:
    if message is None:
        return

    candidates: list[tuple[str, list[Any]]] = []

    text = getattr(message, "text", None)
    if text:
        entities = getattr(message, "entities", None) or []
        candidates.append((text, list(entities)))

    caption = getattr(message, "caption", None)
    if caption:
        caption_entities = getattr(message, "caption_entities", None) or []
        candidates.append((caption, list(caption_entities)))

    for text_value, entities in candidates:
        seen_offsets: set[tuple[int, int]] = set()
        for entity in entities:
            entity_type = getattr(entity, "type", None)
            if entity_type == "text_link":
                url = getattr(entity, "url", None)
                if url:
                    yield url
                continue

            if entity_type == "url":
                offset = getattr(entity, "offset", 0)
                length = getattr(entity, "length", 0)
                key = (offset, length)
                if key in seen_offsets:
                    continue
                seen_offsets.add(key)
                yield text_value[offset : offset + length]

        for match in URL_REGEXP.findall(text_value):
            yield match.rstrip(".,)")


def extract_meme_id_from_message(message: Any) -> int | None:
    for url in _iter_message_urls(message):
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        start_param = query.get("start") or query.get("startapp")
        if not start_param:
            continue

        start_value = start_param[0]
        if not BOT_DEEP_LINK_REGEXP.fullmatch(start_value):
            continue

        meme_id_match = MEME_ID_REGEXP.fullmatch(start_value)
        if meme_id_match:
            return int(meme_id_match.group(1))

    return None


def format_age(published_at: datetime, *, now: datetime | None = None) -> str:
    current_time = now or datetime.utcnow()
    delta = current_time - published_at
    if delta.total_seconds() < 0:
        delta = -delta

    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes = remainder // 60

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours and len(parts) < 2:
        parts.append(f"{hours}h")
    if minutes and len(parts) < 2:
        parts.append(f"{minutes}m")

    if not parts:
        return "< 1m"

    return " ".join(parts)


__all__ = [
    "BOT_DEEP_LINK_REGEXP",
    "MEME_ID_REGEXP",
    "extract_meme_id_from_message",
    "format_age",
    "was_forwarded_from_bot",
]
