"""Event cache and bounded off-request Telegram membership repair.

Feed code reads the database cache only. No subscriber enumeration, messages,
or user creation happens here; Telegram requests concern existing bot users.
"""

import asyncio
import logging
import math
import uuid
from collections import Counter
from datetime import datetime, timedelta

from telegram import Bot, ChatMember
from telegram.error import RetryAfter, TelegramError

from src import redis
from src.tgbot.constants import TELEGRAM_CHANNEL_EN_CHAT_ID, TELEGRAM_CHANNEL_RU_CHAT_ID
from src.tgbot.repo import channel_membership as repository

logger = logging.getLogger(__name__)
OWNED_CHANNELS = {
    "tgchannelru": TELEGRAM_CHANNEL_RU_CHAT_ID,
    "tgchannelen": TELEGRAM_CHANNEL_EN_CHAT_ID,
}
_LEASE_KEY = "channel_membership:repair:lease"
_COOLDOWN_KEY = "channel_membership:repair:cooldown"
_RELEASE_LEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


def membership_status(member: ChatMember) -> str:
    if member.status in {ChatMember.OWNER, ChatMember.ADMINISTRATOR, ChatMember.MEMBER}:
        return "member"
    if member.status in {ChatMember.LEFT, ChatMember.BANNED}:
        return "nonmember"
    if member.status == ChatMember.RESTRICTED:
        if getattr(member, "is_member", None) is True:
            return "member"
        if getattr(member, "is_member", None) is False:
            return "nonmember"
    return "unknown"


async def record_channel_membership_event(
    *,
    user_id: int,
    chat_id: int,
    old_member: ChatMember,
    new_member: ChatMember,
    event_at: datetime,
    update_id: int,
) -> bool:
    if chat_id not in OWNED_CHANNELS.values() or new_member.user.is_bot:
        return False
    if new_member.user.id != user_id:
        raise ValueError("Membership subject must be the changed user")
    return await repository.persist_event(
        user_id,
        chat_id,
        membership_status(new_member),
        membership_status(old_member) == "member",
        event_at,
        update_id,
    )


class _RateLimited(Exception):
    def __init__(self, seconds: float):
        self.seconds = seconds


async def repair_channel_memberships(
    bot: Bot | None = None,
    *,
    limit: int = 100,
    apply: bool = False,
    active_days: int | None = 30,
    refresh_hours: float = 24,
    expected_username: str = "ffmemesbot",
    request_interval: float = 0.5,
) -> dict:
    """One bounded batch. Production callers use run_membership_repair_batch.

    Dry run is DB-only and exports counts. Apply requires identity/admin checks
    before any member lookup. HTTP errors become unknown, never nonmembership.
    """
    if not 1 <= limit <= 10_000 or request_interval < 0:
        raise ValueError("Invalid repair batch limit or request interval")
    if refresh_hours <= 0 or (active_days is not None and active_days <= 0):
        raise ValueError("Invalid repair time window")
    rows = await repository.due_memberships(
        tuple(OWNED_CHANNELS.values()),
        limit=limit,
        active_days=active_days,
    )
    summary = {
        "mode": "apply" if apply else "dry_run",
        "due_pairs": len(rows),
        "checked_pairs": 0,
        "updated_pairs": 0,
        "api_requests": 0,
    }
    if not apply or not rows:
        return summary
    if bot is None:
        raise ValueError("Apply requires a configured Telegram bot")

    async def call(method, **kwargs):
        summary["api_requests"] += 1
        try:
            return await method(**kwargs)
        except RetryAfter as exc:
            delay = exc.retry_after
            seconds = delay.total_seconds() if isinstance(delay, timedelta) else float(delay)
            raise _RateLimited(max(1, seconds)) from None
        finally:
            await asyncio.sleep(request_interval)

    counts = Counter()
    try:
        own = await call(bot.get_me)
        if (own.username or "").lower() != expected_username.lower():
            raise ValueError("Configured Telegram bot identity does not match expected bot")
        administrators = {}
        for chat_id in OWNED_CHANNELS.values():
            try:
                member = await call(bot.get_chat_member, chat_id=chat_id, user_id=own.id)
                administrators[chat_id] = member.status in {
                    ChatMember.ADMINISTRATOR,
                    ChatMember.OWNER,
                }
            except TelegramError:
                administrators[chat_id] = False
            if not administrators[chat_id]:
                await repository.invalidate_channel(chat_id)

        for row in rows:
            requested_at = repository.utc_naive()
            state, error = "unknown", None
            if not administrators[row["chat_id"]]:
                error = "not_administrator"
            else:
                try:
                    member = await call(bot.get_chat_member, **row)
                    state = membership_status(member)
                except TelegramError as exc:
                    error = type(exc).__name__[:40]
            changed = await repository.persist_snapshot(
                row["user_id"],
                row["chat_id"],
                state,
                requested_at,
                error=error,
                refresh_hours=refresh_hours,
            )
            summary["checked_pairs"] += 1
            summary["updated_pairs"] += int(changed)
            counts[state] += 1
    except _RateLimited as exc:
        # The shared runner persists a cooldown for every process. Do not cap
        # RetryAfter or restart a request early when a worker loses its lease.
        summary["retry_after_seconds"] = math.ceil(exc.seconds)
    except TelegramError as exc:
        summary["identity_error"] = type(exc).__name__
    summary["statuses"] = dict(counts)
    return summary


async def run_membership_repair_batch(bot: Bot | None = None, **kwargs) -> dict:
    """Shared lease prevents concurrent webhook workers/backfills flooding API."""
    if not kwargs.get("apply", False):
        return await repair_channel_memberships(bot, **kwargs)
    if await redis.redis_client.exists(_COOLDOWN_KEY):
        return {"mode": "apply", "skipped": "telegram_cooldown"}
    token = str(uuid.uuid4())
    # Bound work below the lease lifetime; cancellation also releases the lease.
    acquired = await redis.redis_client.set(_LEASE_KEY, token, nx=True, ex=300)
    if not acquired:
        return {"mode": "apply", "skipped": "another_worker"}
    try:
        async with asyncio.timeout(240):
            summary = await repair_channel_memberships(bot, **kwargs)
        if delay := summary.get("retry_after_seconds"):
            await redis.redis_client.set(_COOLDOWN_KEY, "1", ex=delay)
        return summary
    finally:
        await redis.redis_client.eval(_RELEASE_LEASE, 1, _LEASE_KEY, token)


async def run_channel_membership_worker(
    bot: Bot,
    *,
    interval_seconds: float = 300,
    batch_size: int = 100,
    refresh_hours: float = 24,
    active_days: int | None = 30,
    expected_username: str = "ffmemesbot",
) -> None:
    """Create/cancel this task in application lifecycle, never in a feed request."""
    if interval_seconds <= 0:
        raise ValueError("Worker interval must be positive")
    while True:
        try:
            result = await run_membership_repair_batch(
                bot,
                limit=batch_size,
                apply=True,
                active_days=active_days,
                refresh_hours=refresh_hours,
                expected_username=expected_username,
            )
            if result.get("checked_pairs") or result.get("identity_error"):
                logger.info("Channel membership repair: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Telegram exception text can contain request details. Log type only.
            logger.warning("Channel membership repair failed (%s)", type(exc).__name__)
        await asyncio.sleep(interval_seconds)
