#!/usr/bin/env python3
"""Export raw layers for bot→channel ML lab (read-only analyst DB).

Two label modes are supported downstream:
  - labels_24h: snapshot closest to +24h in [18h,36h]  (strict, smaller n)
  - labels_lifetime: current crossposting.views/forwards (larger n, ~all history)

Also writes posts with caption sc_ parse for Telethon join audits.

Usage:
  set -a; source .env; set +a
  python export_raw.py --days 0          # all history
  python export_raw.py --days 180
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import asyncpg
except ImportError:
    print("asyncpg required", file=sys.stderr)
    sys.exit(1)

try:
    import polars as pl
except ImportError:
    print("polars required", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"


def _records_to_df(rows: list) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame()
    # Full scan for schema — caption_text / mixed nulls confuse short infer
    return pl.DataFrame([dict(r) for r in rows], infer_schema_length=None)


def _days_clause(days: int, col: str = "cp.created_at") -> str:
    if days and days > 0:
        return f"AND {col} > now() - interval '{int(days)} days'"
    return ""


async def export(days: int) -> dict:
    url = os.environ.get("ANALYST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Set ANALYST_DATABASE_URL or DATABASE_URL")

    RAW.mkdir(parents=True, exist_ok=True)
    conn = await asyncpg.connect(url, statement_cache_size=0)
    meta: dict = {
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "days": days if days > 0 else "all",
        "channel": "tgchannelru",
    }
    dc = _days_clause(days)
    try:
        await conn.execute("SET statement_timeout = '300s'")

        print("posts…")
        posts = await conn.fetch(
            f"""
            SELECT
              cp.meme_id,
              cp.created_at AS posted_at,
              cp.telegram_message_id,
              cp.score_version,
              cp.caption_text,
              cp.caption_text IS NOT NULL AS has_caption_text,
              CASE
                WHEN cp.caption_text ~ 'start=sc_([0-9]+)'
                THEN (regexp_match(cp.caption_text, 'start=sc_([0-9]+)'))[1]::bigint
              END AS caption_sc_meme_id,
              m.language_code,
              m.meme_source_id,
              m.caption IS NOT NULL AS has_caption,
              m.type AS meme_type,
              cp.views AS live_views,
              cp.forwards AS live_forwards,
              cp.reactions AS live_reactions,
              cp.comments AS live_comments,
              cp.stats_updated_at
            FROM crossposting cp
            JOIN meme m ON m.id = cp.meme_id
            WHERE cp.channel = 'tgchannelru'
              {dc}
              AND m.type = 'image'
              AND cp.telegram_message_id IS NOT NULL
            ORDER BY cp.created_at
            """
        )
        posts_df = _records_to_df(posts)
        posts_df.write_parquet(RAW / "posts.parquet")
        meta["n_posts"] = posts_df.height
        print(f"  n_posts={posts_df.height}")

        print("labels_24h (strict snap window)…")
        labels = await conn.fetch(
            f"""
            WITH posts AS (
              SELECT cp.meme_id, cp.created_at AS posted_at, cp.telegram_message_id
              FROM crossposting cp
              JOIN meme m ON m.id = cp.meme_id
              WHERE cp.channel = 'tgchannelru'
                {dc}
                AND cp.created_at < now() - interval '36 hours'
                AND m.type = 'image'
                AND cp.telegram_message_id IS NOT NULL
            )
            SELECT DISTINCT ON (p.meme_id)
              p.meme_id,
              p.posted_at,
              s.views AS views_24h,
              s.forwards AS forwards_24h,
              s.reactions AS reactions_24h,
              s.comments AS comments_24h,
              1000.0 * s.forwards / NULLIF(s.views, 0) AS f1k_24h,
              s.snapshot_at,
              'snap_18_36h'::text AS label_source
            FROM posts p
            JOIN crossposting_snapshots s
              ON s.channel = 'tgchannelru'
             AND s.telegram_message_id = p.telegram_message_id
             AND s.snapshot_at BETWEEN p.posted_at + interval '18 hours'
                                   AND p.posted_at + interval '36 hours'
             AND s.views > 0
            ORDER BY p.meme_id,
              abs(extract(epoch from (s.snapshot_at - (p.posted_at + interval '24 hours'))))
            """
        )
        labels_df = _records_to_df(labels)
        labels_df.write_parquet(RAW / "labels_24h.parquet")
        meta["n_labels_24h"] = labels_df.height
        print(f"  n_labels_24h={labels_df.height}")

        print("labels_lifetime (live columns on crossposting)…")
        life = await conn.fetch(
            f"""
            SELECT
              cp.meme_id,
              cp.created_at AS posted_at,
              cp.views AS views_life,
              cp.forwards AS forwards_life,
              cp.reactions AS reactions_life,
              cp.comments AS comments_life,
              1000.0 * cp.forwards / NULLIF(cp.views, 0) AS f1k_life,
              cp.stats_updated_at,
              'crossposting_live'::text AS label_source
            FROM crossposting cp
            JOIN meme m ON m.id = cp.meme_id
            WHERE cp.channel = 'tgchannelru'
              {dc}
              AND cp.created_at < now() - interval '36 hours'
              AND m.type = 'image'
              AND cp.telegram_message_id IS NOT NULL
              AND cp.views IS NOT NULL AND cp.views > 0
            """
        )
        life_df = _records_to_df(life)
        life_df.write_parquet(RAW / "labels_lifetime.parquet")
        meta["n_labels_lifetime"] = life_df.height
        print(f"  n_labels_lifetime={life_df.height}")

        print("channel_history (for source prior)…")
        hist_days = max(days * 2, 720) if days > 0 else 0
        hdc = _days_clause(hist_days) if hist_days else ""
        hist = await conn.fetch(
            f"""
            WITH posts AS (
              SELECT cp.meme_id, cp.created_at AS posted_at, cp.telegram_message_id, m.meme_source_id,
                     cp.views, cp.forwards, cp.reactions
              FROM crossposting cp
              JOIN meme m ON m.id = cp.meme_id
              WHERE cp.channel = 'tgchannelru'
                {hdc}
                AND m.type = 'image'
                AND cp.telegram_message_id IS NOT NULL
                AND cp.views IS NOT NULL AND cp.views > 0
            )
            SELECT
              meme_id, posted_at, meme_source_id,
              views, forwards, reactions,
              1000.0 * forwards / NULLIF(views, 0) AS f1k
            FROM posts
            """
        )
        hist_df = _records_to_df(hist)
        hist_df.write_parquet(RAW / "channel_history.parquet")
        meta["n_channel_history"] = hist_df.height
        print(f"  n_channel_history={hist_df.height}")

        print("reactions_pre (can be large)…")
        dc_plain = _days_clause(days, col="created_at")
        reacts = await conn.fetch(
            f"""
            SELECT
              umr.user_id,
              umr.meme_id,
              umr.reaction_id,
              umr.reacted_at,
              umr.sent_at,
              CASE
                WHEN umr.sent_at IS NOT NULL AND umr.reacted_at IS NOT NULL
                THEN extract(epoch from (umr.reacted_at - umr.sent_at))
              END AS sec_to_react
            FROM user_meme_reaction umr
            JOIN (
              SELECT meme_id, created_at AS posted_at
              FROM crossposting
              WHERE channel = 'tgchannelru'
                {dc_plain}
            ) p ON p.meme_id = umr.meme_id
            WHERE umr.reacted_at < p.posted_at
            """
        )
        reacts_df = _records_to_df(reacts)
        reacts_df.write_parquet(RAW / "reactions_pre.parquet")
        meta["n_reactions_pre"] = reacts_df.height
        print(f"  n_reactions_pre={reacts_df.height}")

        if reacts_df.height:
            user_ids = reacts_df["user_id"].unique().to_list()
        else:
            user_ids = []
        print(f"users_tg for {len(user_ids)} reactors…")
        if user_ids:
            chunks = []
            for i in range(0, len(user_ids), 5000):
                batch = user_ids[i : i + 5000]
                rows = await conn.fetch(
                    """
                    SELECT id AS user_id, is_premium, language_code
                    FROM user_tg WHERE id = ANY($1::bigint[])
                    """,
                    batch,
                )
                chunks.extend(rows)
            ut_df = _records_to_df(chunks)
        else:
            ut_df = pl.DataFrame(
                schema={"user_id": pl.Int64, "is_premium": pl.Boolean, "language_code": pl.Utf8}
            )
        ut_df.write_parquet(RAW / "users_tg.parquet")
        meta["n_users_tg"] = ut_df.height

        print("users type…")
        if user_ids:
            chunks = []
            for i in range(0, len(user_ids), 5000):
                batch = user_ids[i : i + 5000]
                rows = await conn.fetch(
                    """
                    SELECT id AS user_id, type, balance
                    FROM "user" WHERE id = ANY($1::bigint[])
                    """,
                    batch,
                )
                chunks.extend(rows)
            u_df = _records_to_df(chunks)
        else:
            u_df = pl.DataFrame(
                schema={"user_id": pl.Int64, "type": pl.Utf8, "balance": pl.Int64}
            )
        u_df.write_parquet(RAW / "users.parquet")
        meta["n_users"] = u_df.height

        print("meme_source_stats…")
        mss = await conn.fetch(
            """
            SELECT meme_source_id, nlikes, ndislikes, nmemes_sent, nmemes_sent_events,
                   nmemes_parsed, latest_meme_age
            FROM meme_source_stats
            """
        )
        mss_df = _records_to_df(mss)
        mss_df.write_parquet(RAW / "meme_source_stats.parquet")
        meta["n_meme_source_stats"] = mss_df.height

        (ROOT / "data" / "export_meta.json").write_text(json.dumps(meta, indent=2, default=str))
        print("done", meta)
        return meta
    finally:
        await conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--days",
        type=int,
        default=0,
        help="History window in days; 0 = all available (recommended for lifetime labels)",
    )
    args = ap.parse_args()
    asyncio.run(export(args.days))


if __name__ == "__main__":
    main()
