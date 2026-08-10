#!/usr/bin/env python3
"""Recompute RU taste cohort (top-50) from analyst/prod DB (read-only).

Writes src/crossposting/data/ru_taste_cohort_v1.json for shadow logging.

Usage:
  set -a; source .env; set +a
  python scripts/crosspost_taste_cohort.py
  python scripts/crosspost_taste_cohort.py --top 50 --min-n 8 --days 120
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    import asyncpg
except ImportError:
    print("asyncpg required", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "crossposting" / "data" / "ru_taste_cohort_v1.json"


async def run(*, days: int, top: int, min_n: int) -> dict:
    url = os.environ.get("ANALYST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Set ANALYST_DATABASE_URL or DATABASE_URL")

    conn = await asyncpg.connect(url, statement_cache_size=0)
    try:
        await conn.execute("SET statement_timeout = '180s'")
        posts = await conn.fetch(
            f"""
            WITH posts AS (
              SELECT cp.meme_id, cp.created_at AS posted_at, cp.telegram_message_id
              FROM crossposting cp
              JOIN meme m ON m.id = cp.meme_id
              WHERE cp.channel = 'tgchannelru'
                AND cp.created_at > now() - interval '{int(days)} days'
                AND cp.created_at < now() - interval '36 hours'
                AND m.type = 'image'
                AND cp.telegram_message_id IS NOT NULL
            ),
            labels AS (
              SELECT DISTINCT ON (p.meme_id)
                p.meme_id, p.posted_at,
                1000.0 * s.forwards / NULLIF(s.views, 0) AS f1k
              FROM posts p
              JOIN crossposting_snapshots s
                ON s.channel = 'tgchannelru'
               AND s.telegram_message_id = p.telegram_message_id
               AND s.snapshot_at BETWEEN p.posted_at + interval '18 hours'
                                     AND p.posted_at + interval '36 hours'
               AND s.views > 0
              ORDER BY p.meme_id,
                abs(extract(epoch from (
                  s.snapshot_at - (p.posted_at + interval '24 hours')
                )))
            )
            SELECT * FROM labels ORDER BY posted_at
            """
        )
        if len(posts) < 50:
            raise SystemExit(f"too few labeled posts: {len(posts)}")

        meme_ids = [r["meme_id"] for r in posts]
        likes = await conn.fetch(
            """
            SELECT umr.user_id, umr.meme_id
            FROM user_meme_reaction umr
            JOIN (
              SELECT meme_id, created_at AS posted_at FROM crossposting
              WHERE channel='tgchannelru' AND meme_id = ANY($1::bigint[])
            ) o ON o.meme_id = umr.meme_id
            WHERE umr.reaction_id = 1
              AND umr.reacted_at IS NOT NULL
              AND umr.reacted_at < o.posted_at
              AND umr.meme_id = ANY($1::bigint[])
            """,
            meme_ids,
        )
    finally:
        await conn.close()

    post_by_id = {r["meme_id"]: r for r in posts}
    base = sum(float(r["f1k"]) for r in posts) / len(posts)
    posts_sorted = sorted(posts, key=lambda r: r["posted_at"])
    cut = posts_sorted[int(len(posts_sorted) * 0.7)]["posted_at"]
    train = {r["meme_id"] for r in posts_sorted if r["posted_at"] < cut}

    train_user: dict[int, list[float]] = defaultdict(list)
    for edge in likes:
        if edge["meme_id"] not in train:
            continue
        train_user[edge["user_id"]].append(float(post_by_id[edge["meme_id"]]["f1k"]))

    scored = []
    for uid, vals in train_user.items():
        if len(vals) < min_n:
            continue
        avg = sum(vals) / len(vals)
        scored.append((uid, avg / base, len(vals), avg))
    scored.sort(key=lambda x: (-x[1], -x[2]))
    top = scored[:top]

    payload = {
        "version": "ru_taste_cohort_v1",
        "channel": "tgchannelru",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "method": f"train_70pct_time_split_avg_f1k_lift_min_n{min_n}",
        "train_cut": cut.isoformat(),
        "base_f1k": round(base, 4),
        "n_labeled_posts": len(posts),
        "days": days,
        "users": [
            {
                "user_id": uid,
                "lift": round(lift, 4),
                "n_train": n,
                "avg_f1k": round(avg, 2),
            }
            for uid, lift, n, avg in top
        ],
        "user_ids": [uid for uid, *_ in top],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {OUT} n_users={len(payload['user_ids'])} base_f1k={base:.2f}")
    return payload


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--days", type=int, default=120)
    p.add_argument("--top", type=int, default=50)
    p.add_argument("--min-n", type=int, default=8)
    args = p.parse_args()
    asyncio.run(run(days=args.days, top=args.top, min_n=args.min_n))


if __name__ == "__main__":
    main()
