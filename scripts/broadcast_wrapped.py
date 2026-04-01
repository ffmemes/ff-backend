"""
Broadcast wrapped notification to all qualified users.

Run inside the app container:
    docker compose exec app python scripts/broadcast_wrapped.py

Or with --dry-run to preview without sending:
    docker compose exec app python scripts/broadcast_wrapped.py --dry-run
"""

import asyncio
import sys

from sqlalchemy import text

from src.database import execute, fetch_all
from src.localizer import ALMOST_CIS_LANGUAGES
from src.tgbot.bot import bot

# Only send to users who can actually complete wrapped:
# - not blocked/waitlist
# - active in last 90 days
# - >=30 memes seen
# - >=5 liked memes with OCR descriptions
QUALIFIED_USERS_QUERY = text("""
    SELECT
        us.user_id,
        COALESCE(ut.language_code, 'en') AS language_code
    FROM user_stats us
    JOIN "user" u ON u.id = us.user_id
    LEFT JOIN user_tg ut ON ut.id = us.user_id
    WHERE u.type NOT IN ('waitlist', 'blocked_bot')
      AND u.last_active_at > now() - interval '90 days'
      AND us.nmemes_sent >= 30
      AND (
          SELECT count(*)
          FROM user_meme_reaction umr
          JOIN meme m ON m.id = umr.meme_id
          WHERE umr.user_id = us.user_id
            AND umr.reaction_id = 1
            AND m.ocr_result IS NOT NULL
      ) >= 5
    ORDER BY u.last_active_at DESC
""")

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

SEND_DELAY = 0.05  # 50ms between sends (~20/sec, well within TG limits)


async def main():
    dry_run = "--dry-run" in sys.argv

    rows = await fetch_all(QUALIFIED_USERS_QUERY)
    ru_users = [r for r in rows if r["language_code"] in ALMOST_CIS_LANGUAGES]
    en_users = [r for r in rows if r["language_code"] not in ALMOST_CIS_LANGUAGES]

    print(f"Qualified users: {len(rows)} total ({len(ru_users)} RU, {len(en_users)} EN)")

    if dry_run:
        print("\n--- DRY RUN (no messages sent) ---")
        print(f"\nRU message ({len(ru_users)} users):\n{MESSAGE_RU}")
        print(f"\nEN message ({len(en_users)} users):\n{MESSAGE_EN}")
        return

    sent = 0
    failed = 0
    blocked = 0

    for user_list, message in [(ru_users, MESSAGE_RU), (en_users, MESSAGE_EN)]:
        for row in user_list:
            user_id = row["user_id"]
            try:
                await bot.send_message(chat_id=user_id, text=message)
                sent += 1
                if sent % 50 == 0:
                    print(f"  sent: {sent}, failed: {failed}, blocked: {blocked}")
            except Exception as e:
                err = str(e).lower()
                if "blocked" in err or "deactivated" in err or "not found" in err:
                    blocked += 1
                    # Mark user as blocked_bot
                    await execute(
                        text("UPDATE \"user\" SET type = 'blocked_bot' WHERE id = :uid"),
                        {"uid": user_id},
                    )
                else:
                    failed += 1
                    print(f"  error for {user_id}: {e}")

            await asyncio.sleep(SEND_DELAY)

    print(f"\nDone! Sent: {sent}, Blocked: {blocked}, Failed: {failed}")


if __name__ == "__main__":
    asyncio.run(main())
