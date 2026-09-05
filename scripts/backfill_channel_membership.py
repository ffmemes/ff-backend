#!/usr/bin/env python3
"""Bounded membership bootstrap/repair. Default dry run performs no Telegram calls.

Run in the owning application's configured environment. Never pass credentials
as CLI arguments. --apply uses the same shared lease as the background worker.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist verified membership states")
    parser.add_argument("--limit", type=int, default=100, help="Maximum user/channel pairs")
    parser.add_argument(
        "--active-days",
        type=int,
        default=30,
        help="Known users active within this many days; 0 includes all",
    )
    parser.add_argument("--refresh-hours", type=float, default=24)
    parser.add_argument("--expected-username", default="ffmemesbot")
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 10_000 or args.active_days < 0 or args.refresh_hours <= 0:
        parser.error("Invalid limit or time window")
    return args


async def run(args) -> dict:
    from src import redis
    from src.config import settings
    from src.database import engine
    from src.tgbot.channel_membership import run_membership_repair_batch

    options = dict(
        limit=args.limit,
        apply=args.apply,
        active_days=args.active_days or None,
        refresh_hours=args.refresh_hours,
        expected_username=args.expected_username,
    )
    try:
        if not args.apply:
            return await run_membership_repair_batch(**options)
        from telegram import Bot

        if not settings.TELEGRAM_BOT_TOKEN:
            raise ValueError("Configured bot credential is missing")
        async with Bot(settings.TELEGRAM_BOT_TOKEN) as bot:
            return await run_membership_repair_batch(bot, **options)
    finally:
        await engine.dispose()
        await redis.pool.disconnect()


def main() -> None:
    try:
        print(json.dumps(asyncio.run(run(parse_args())), sort_keys=True))
    except KeyboardInterrupt:
        raise SystemExit("Membership repair interrupted") from None
    except Exception as exc:
        # Never print request URLs, bot credentials, or individual member IDs.
        raise SystemExit("Membership repair failed: " + type(exc).__name__) from None


if __name__ == "__main__":
    main()
