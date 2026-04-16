import asyncio
import logging

from sqlalchemy import text
from telegram.error import BadRequest, Forbidden, RetryAfter

from src.database import execute, fetch_all
from src.redis import redis_client
from src.tgbot.bot import bot

logger = logging.getLogger(__name__)


# ── User queries ────────────────────────────────────────


async def get_user_ids_active_minutes_ago(
    from_minutes_ago: int,
    to_minutes_ago: int,
) -> list[int]:
    assert from_minutes_ago < to_minutes_ago
    insert_query = f"""
        SELECT
            id
        FROM "user"
        WHERE 1=1
            AND type NOT IN ('waitlist', 'blocked_bot')
            AND last_active_at BETWEEN
                NOW() - INTERVAL '{to_minutes_ago} MINUTES'
                AND
                NOW() - INTERVAL '{from_minutes_ago} MINUTES'
    """
    res = await fetch_all(text(insert_query))
    return [r["id"] for r in res]


async def get_users_to_broadcast_meme_from_tgchannelru(
    meme_id: int,
):
    # select users
    # 1. with language ru
    # 2. who hadn't followed the channel
    # 3. who didn't watch the meme

    select_query = f"""
        SELECT DISTINCT UL.user_id
        FROM user_language UL
        LEFT JOIN user_meme_reaction UMR
            ON UMR.user_id = UL.user_id
            AND UMR.meme_id = {meme_id}
        LEFT JOIN user_tg_chat_membership UTCM
            ON UTCM.user_tg_id = UL.user_id
        WHERE 1=1
            AND UL.language_code = 'ru'
            AND UMR.user_id IS NULL
            AND UTCM.user_tg_id IS NULL
    """

    return await fetch_all(text(select_query))


async def get_users_to_broadcast_post_from_tgchannelru():
    # select users
    # 1. with language ru
    # 2. who hadn't followed the channel

    select_query = """
        SELECT DISTINCT UL.user_id
        FROM user_language UL
        LEFT JOIN user_tg_chat_membership UTCM
            ON UTCM.user_tg_id = UL.user_id
        WHERE 1=1
            AND UL.language_code = 'ru'
            AND UTCM.user_tg_id IS NULL
    """

    return await fetch_all(text(select_query))


async def get_users_with_language(
    language_code: str,
):
    select_query = f"""
        SELECT user_id
        FROM user_language
        WHERE language_code = '{language_code}'
    """
    return await fetch_all(text(select_query))


async def get_users_active_more_than_days_ago(
    days_ago: int,
):
    select_query = f"""
        SELECT id
        FROM "user"
        WHERE last_active_at < NOW() - INTERVAL '{days_ago} DAYS'
        AND type != 'blocked_bot'
    """
    return await fetch_all(text(select_query))


async def get_all_non_blocked_users() -> list[dict]:
    """Get all users with their bot content language (from user_language table).

    Uses user_language (bot preference) over user_tg.language_code (Telegram app).
    A user with Telegram in English but bot content in Russian gets language_code='ru'.
    """
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
        WHERE u.type NOT IN ('waitlist', 'blocked_bot')
        ORDER BY u.last_active_at DESC
    """
        )
    )


# ── Broadcast engine ────────────────────────────────────


def _broadcast_redis_key(broadcast_id: str) -> str:
    return f"broadcast:{broadcast_id}:sent"


async def send_broadcast(
    broadcast_id: str,
    users: list[dict],
    messages: dict[str, str],
    language_fn,
    delay: float = 0.15,
    dry_run: bool = False,
) -> dict:
    """
    Send a text broadcast to a list of users with dedup via Redis.

    Args:
        broadcast_id: Unique ID for this broadcast (e.g. "wrapped-2026-04-01").
                      Re-running with the same ID skips already-sent users.
        users: List of dicts with at least "user_id" and "language_code" keys.
        messages: Dict mapping language group to message text, e.g.
                  {"ru": "...", "en": "..."}.
        language_fn: Function(language_code) -> message key from messages dict.
        delay: Seconds between sends. 0.15 = ~7/sec.
        dry_run: If True, print stats but don't send.

    Returns:
        {"sent": N, "blocked": N, "failed": N, "skipped": N}
    """
    redis_key = _broadcast_redis_key(broadcast_id)
    already_sent = await redis_client.scard(redis_key)

    print(f"Broadcast '{broadcast_id}': {len(users)} users, {already_sent} already sent")

    if dry_run:
        print("--- DRY RUN ---")
        for msg_key, msg_text in messages.items():
            count = sum(1 for u in users if language_fn(u["language_code"]) == msg_key)
            print(f"\n{msg_key} ({count} users):\n{msg_text}")
        return {"sent": 0, "blocked": 0, "failed": 0, "skipped": int(already_sent)}

    sent = 0
    blocked = 0
    failed = 0
    skipped = 0

    for row in users:
        user_id = row["user_id"]

        # Dedup: skip if already sent in this broadcast
        if await redis_client.sismember(redis_key, str(user_id)):
            skipped += 1
            continue

        msg_key = language_fn(row["language_code"])
        message = messages.get(msg_key, messages.get("en", ""))

        try:
            await bot.send_message(chat_id=user_id, text=message)
            sent += 1
            await redis_client.sadd(redis_key, str(user_id))

            if sent % 100 == 0:
                print(f"  sent:{sent} blocked:{blocked} failed:{failed} skipped:{skipped}")

        except (Forbidden, BadRequest) as e:
            err_msg = str(e).lower()
            if isinstance(e, Forbidden) or "not found" in err_msg:
                blocked += 1
                await redis_client.sadd(redis_key, str(user_id))
                await execute(
                    text("UPDATE \"user\" SET type = 'blocked_bot' WHERE id = :uid"),
                    {"uid": user_id},
                )
            else:
                failed += 1
                if failed <= 10:
                    logger.warning("Broadcast %s error for %d: %s", broadcast_id, user_id, e)
        except RetryAfter as e:
            sleep_for = e.retry_after + 1
            print(f"  rate limited, sleeping {sleep_for}s...")
            await asyncio.sleep(sleep_for)
            try:
                await bot.send_message(chat_id=user_id, text=message)
                sent += 1
                await redis_client.sadd(redis_key, str(user_id))
            except Exception:
                failed += 1
        except Exception as e:
            failed += 1
            if failed <= 10:
                logger.warning("Broadcast %s error for %d: %s", broadcast_id, user_id, e)

        await asyncio.sleep(delay)

    result = {"sent": sent, "blocked": blocked, "failed": failed, "skipped": skipped}
    print(f"\nDone! {result}")
    return result
