"""Backfill meme.image_hash (dHash) for recent live image memes.

Measurement only: stores hashes and logs "phash shadow match" lines; never
merges. Resumable (only image_hash IS NULL rows). Videos/animations are skipped:
their Telegram thumbnail file_id is not stored, so v1 only hashes new uploads.

    docker compose exec app python -m scripts.admin.backfill_image_hash --days 30 --limit 5000
"""

import argparse
import asyncio
import json
import logging

from sqlalchemy import text

from src.database import fetch_all
from src.storage.deduplication.image_hash import dhash, log_phash_shadow_match
from src.storage.service import update_meme
from src.storage.upload import download_meme_content_from_tg


async def _run(days: int, limit: int, rate: float) -> dict[str, int]:
    rows = await fetch_all(
        text(
            """
            SELECT id, telegram_file_id FROM meme
            WHERE status IN ('ok', 'published')
              AND type = 'image'
              AND image_hash IS NULL
              AND telegram_file_id IS NOT NULL
              AND created_at >= NOW() - make_interval(days => :days)
            ORDER BY id DESC
            LIMIT :limit
            """
        ),
        {"days": days, "limit": limit},
    )
    counts = {"selected": len(rows), "hashed": 0, "failed": 0, "shadow_matches": 0}
    for row in rows:
        await asyncio.sleep(1 / rate)
        try:
            content = await download_meme_content_from_tg(row["telegram_file_id"])
            meme = await update_meme(row["id"], image_hash=dhash(content))
        except Exception as e:
            logging.warning("meme %s: hash failed: %s", row["id"], e)
            counts["failed"] += 1
            continue
        counts["hashed"] += 1
        if await log_phash_shadow_match(meme):
            counts["shadow_matches"] += 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m scripts.admin.backfill_image_hash")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--rate", type=float, default=20.0, help="max files per second")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(asyncio.run(_run(args.days, args.limit, args.rate))))


if __name__ == "__main__":
    main()
