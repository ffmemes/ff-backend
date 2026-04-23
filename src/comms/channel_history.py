"""
Read recent @ffmemes channel post history via Telethon.

Bot API cannot read a channel's own post history, so Comms Agent uses the
existing Telethon session (same one used by crossposting stats collector)
to pull the last N posts and enforce topic rotation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from telethon import TelegramClient
from telethon.sessions import StringSession

from src.config import settings

logger = logging.getLogger(__name__)

FFMEMES_USERNAME = "fastfoodmemes"  # @ffmemes (Russian channel)


@dataclass
class RecentPost:
    message_id: int
    date: datetime
    text: str
    first_line: str
    has_media: bool


def _get_client() -> TelegramClient | None:
    if not all(
        [
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH,
            settings.TELEGRAM_SESSION_STRING,
        ]
    ):
        return None
    return TelegramClient(
        StringSession(settings.TELEGRAM_SESSION_STRING),
        settings.TELEGRAM_API_ID,
        settings.TELEGRAM_API_HASH,
    )


async def get_last_n_posts(n: int = 7, channel: str = FFMEMES_USERNAME) -> list[RecentPost]:
    """
    Fetch the N most recent posts from a public channel.

    Returns [] if Telethon is not configured or the session is dead; callers
    should treat an empty list as "rotation check unavailable" and still post
    (failing closed would block the channel).
    """
    client = _get_client()
    if client is None:
        logger.warning("Telethon not configured — channel history unavailable")
        return []

    try:
        await client.connect()
        if not await client.is_user_authorized():
            logger.error(
                "Telethon session expired. Regenerate with "
                "`python scripts/generate_session_string.py`."
            )
            return []

        entity = await client.get_entity(channel)
        messages = await client.get_messages(entity, limit=n)

        out: list[RecentPost] = []
        for m in messages:
            if m is None:
                continue
            text = (m.text or m.message or "").strip()
            first_line = text.split("\n", 1)[0][:200] if text else ""
            out.append(
                RecentPost(
                    message_id=m.id,
                    date=m.date.replace(tzinfo=None) if m.date else datetime.utcnow(),
                    text=text[:2000],
                    first_line=first_line,
                    has_media=bool(getattr(m, "media", None)),
                )
            )
        return out

    except Exception as e:
        logger.error(f"Failed to fetch @{channel} history: {e}")
        return []
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
