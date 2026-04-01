"""
Broadcast wrapped notification to users.

Uses Redis-based dedup — safe to re-run (skips already-sent users).

    PYTHONPATH=/src python scripts/broadcast_wrapped.py wrapped-apr2026
    PYTHONPATH=/src python scripts/broadcast_wrapped.py wrapped-apr2026 --dry-run
    PYTHONPATH=/src python scripts/broadcast_wrapped.py wrapped-apr2026 --delay 0.3
"""

import asyncio
import sys

from src.broadcasts.service import get_all_non_blocked_users, send_broadcast
from src.localizer import ALMOST_CIS_LANGUAGES

MESSAGE_RU = (
    "🔮 Мы подготовили глубокий анализ твоего чувства юмора "
    "на основе твоих лайков.\n\n"
    "Мем-зодиак, ДНК юмора, абсурдные сравнения "
    "и предсказание на лето.\n\n"
    "Жми 👉 /wrapped"
)

MESSAGE_EN = (
    "🔮 We've prepared a deep analysis of your sense of humor "
    "based on your likes.\n\n"
    "Meme zodiac, humor DNA, absurd comparisons "
    "and a summer prediction.\n\n"
    "Try it 👉 /wrapped"
)


def _lang_group(language_code: str) -> str:
    return "ru" if language_code in ALMOST_CIS_LANGUAGES else "en"


async def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("Usage: broadcast_wrapped.py <broadcast_id> [--dry-run] [--delay 0.15]")
        print("  broadcast_id is required (e.g. 'wrapped-apr2026')")
        print("  Re-running with the same ID safely skips already-sent users.")
        sys.exit(1)

    broadcast_id = args[0]
    dry_run = "--dry-run" in sys.argv

    delay = 0.15
    if "--delay" in sys.argv:
        idx = sys.argv.index("--delay")
        delay = float(sys.argv[idx + 1])

    users = await get_all_non_blocked_users()
    await send_broadcast(
        broadcast_id=broadcast_id,
        users=users,
        messages={"ru": MESSAGE_RU, "en": MESSAGE_EN},
        language_fn=_lang_group,
        delay=delay,
        dry_run=dry_run,
    )


if __name__ == "__main__":
    asyncio.run(main())
