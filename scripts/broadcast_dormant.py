"""One-shot meme broadcast to users idle for at least N days.

Picks a per-user meme (channel-viral last 7 days, then HQ, then queue).
Redis dedup via broadcast_id — safe to re-run.

    PYTHONPATH=/src python scripts/broadcast_dormant.py dormant-channel-viral-2026-09-07
    PYTHONPATH=/src python scripts/broadcast_dormant.py dormant-channel-viral-2026-09-07 --dry-run
    PYTHONPATH=/src python scripts/broadcast_dormant.py dormant-channel-viral-2026-09-07 --delay 0.3
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from src.broadcasts.service import get_users_inactive_since_days, send_meme_broadcast


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("broadcast_id", help="Unique id; reuse to resume after a crash")
    parser.add_argument("--min-days", type=int, default=7)
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument("--dry-run", action="store_true")
    return parser


async def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.min_days < 1:
        print("min-days must be >= 1", file=sys.stderr)
        return 2
    user_ids = await get_users_inactive_since_days(args.min_days)
    print(f"Idle >= {args.min_days}d: {len(user_ids)} users")
    await send_meme_broadcast(
        broadcast_id=args.broadcast_id,
        user_ids=user_ids,
        delay=args.delay,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
