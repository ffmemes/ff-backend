#!/usr/bin/env python3
"""Densify user_tg_chat_membership for @fastfoodmemes / EN channel.

Checks getChatMember for recently active bot users and upserts/removes membership
rows. Improves H9 (subscriber ∩ bot) coverage for offline/online shadow features.

Usage (prod or staging with real bot token + DB):
  set -a; source .env; set +a
  python scripts/sync_channel_membership.py --channel ru --limit 500 --sleep 0.05
  python scripts/sync_channel_membership.py --channel ru --limit 2000 --dry-run

Telegram rate limits: keep sleep >= 0.05s; default limit 500/run.
Schedule manually or via cron/Prefect later — not auto-wired.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# repo root on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import telegram
from sqlalchemy import text
from telegram.constants import ChatMemberStatus

from src.config import settings
from src.database import execute, fetch_all
from src.tgbot.constants import TELEGRAM_CHANNEL_EN_CHAT_ID, TELEGRAM_CHANNEL_RU_CHAT_ID
from src.tgbot.repo.users import add_user_tg_chat_membership

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sync_channel_membership")

MEMBER_OK = {
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.OWNER,
    ChatMemberStatus.RESTRICTED,  # still in channel
}


async def _active_user_ids(limit: int, days: int) -> list[int]:
    rows = await fetch_all(
        text(
            """
            SELECT user_id, count(*)::int AS n
            FROM user_meme_reaction
            WHERE reacted_at > now() - make_interval(days => :days)
            GROUP BY user_id
            ORDER BY n DESC
            LIMIT :limit
            """
        ),
        {"days": days, "limit": limit},
    )
    return [int(r["user_id"]) for r in rows]


async def _delete_membership(user_id: int, chat_id: int) -> None:
    await execute(
        text(
            """
            DELETE FROM user_tg_chat_membership
            WHERE user_tg_id = :uid AND chat_id = :chat_id
            """
        ),
        {"uid": user_id, "chat_id": chat_id},
    )


async def sync(
    *,
    channel: str,
    limit: int,
    days: int,
    sleep_s: float,
    dry_run: bool,
) -> dict:
    chat_id = TELEGRAM_CHANNEL_RU_CHAT_ID if channel == "ru" else TELEGRAM_CHANNEL_EN_CHAT_ID
    if not settings.TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN required")

    bot = telegram.Bot(settings.TELEGRAM_BOT_TOKEN)
    user_ids = await _active_user_ids(limit, days)
    log.info("checking %s users for chat_id=%s dry_run=%s", len(user_ids), chat_id, dry_run)

    stats = {
        "checked": 0,
        "member": 0,
        "not_member": 0,
        "errors": 0,
        "added_or_refreshed": 0,
        "removed": 0,
        "chat_id": chat_id,
        "channel": channel,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    for uid in user_ids:
        stats["checked"] += 1
        try:
            res = await bot.get_chat_member(chat_id, uid)
            is_member = res.status in MEMBER_OK
            if is_member:
                stats["member"] += 1
                if not dry_run:
                    await add_user_tg_chat_membership(uid, chat_id)
                    stats["added_or_refreshed"] += 1
            else:
                stats["not_member"] += 1
                if not dry_run:
                    await _delete_membership(uid, chat_id)
                    stats["removed"] += 1
        except telegram.error.RetryAfter as e:
            wait = float(getattr(e, "retry_after", 1) or 1)
            log.warning("RetryAfter %ss", wait)
            await asyncio.sleep(wait + 0.1)
            stats["errors"] += 1
        except telegram.error.TelegramError as e:
            # user not found / blocked / etc.
            stats["errors"] += 1
            if stats["errors"] <= 5 or stats["errors"] % 50 == 0:
                log.warning("user %s: %s", uid, e)
        if sleep_s > 0:
            await asyncio.sleep(sleep_s)
        if stats["checked"] % 100 == 0:
            log.info("progress %s %s", stats["checked"], stats)

    stats["finished_at"] = datetime.now(timezone.utc).isoformat()
    log.info("done %s", stats)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", choices=("ru", "en"), default="ru")
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--days", type=int, default=30, help="active users lookback")
    ap.add_argument("--sleep", type=float, default=0.05, dest="sleep_s")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    asyncio.run(
        sync(
            channel=args.channel,
            limit=args.limit,
            days=args.days,
            sleep_s=args.sleep_s,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
