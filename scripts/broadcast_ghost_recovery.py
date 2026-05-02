"""
Broadcast a recovery message to ghost users — registered ≤12 months ago,
never had a single meme delivered (no row in user_meme_reaction), not
blocked. They were silently locked out by onboarding bugs (kitchen
deep_link missed init_user_languages_from_tg_user; April 2026 cohort
hit a 9.4% no-delivery rate vs ~3-5% baseline). PR #222 fixes the leak
forward; this script recovers existing ghosts.

Reuses src.broadcasts.service.send_broadcast — same Redis dedup,
Forbidden handling, rate limiting as broadcast_wrapped.py.

    PYTHONPATH=/src python scripts/broadcast_ghost_recovery.py ghost-recovery-2026-05 --dry-run
    PYTHONPATH=/src python scripts/broadcast_ghost_recovery.py ghost-recovery-2026-05 --delay 0.5

Re-running with the same broadcast_id is safe (skips already-sent).
"""

import asyncio
import sys

from sqlalchemy import text

from src.broadcasts.service import send_broadcast
from src.database import fetch_all
from src.localizer import ALMOST_CIS_LANGUAGES

MESSAGE_RU = (
    "Привет! У нас был баг в боте: мемы тебе не приходили, хотя ты подписался. "
    "Только что починили. Жми /start — и поедут. 🍔"
)

MESSAGE_EN = (
    "Hey! Sorry — there was a bug in the bot: you signed up but never got any memes. "
    "Just fixed it. Hit /start to start the flow. 🍔"
)


def _lang_group(language_code: str | None) -> str:
    return "ru" if language_code in ALMOST_CIS_LANGUAGES else "en"


async def get_ghost_users() -> list[dict]:
    """Registered ≤12mo, never delivered a meme, not blocked, not waitlisted."""
    return await fetch_all(
        text(
            """
        SELECT u.id AS user_id,
               COALESCE(
                   (SELECT ul.language_code FROM user_language ul
                    WHERE ul.user_id = u.id LIMIT 1),
                   ut.language_code,
                   'en'
               ) AS language_code
        FROM "user" u
        LEFT JOIN user_tg ut ON ut.id = u.id
        WHERE u.created_at > NOW() - INTERVAL '12 months'
          AND u.blocked_bot_at IS NULL
          AND u.type NOT IN ('blocked_bot', 'waitlist')
          AND NOT EXISTS (
              SELECT 1 FROM user_meme_reaction r WHERE r.user_id = u.id
          )
        ORDER BY u.created_at DESC
    """
        )
    )


async def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("Usage: broadcast_ghost_recovery.py <broadcast_id> [--dry-run] [--delay 0.5]")
        sys.exit(1)

    broadcast_id = args[0]
    dry_run = "--dry-run" in sys.argv

    delay = 0.5
    if "--delay" in sys.argv:
        idx = sys.argv.index("--delay")
        delay = float(sys.argv[idx + 1])

    users = await get_ghost_users()
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
