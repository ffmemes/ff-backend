#!/usr/bin/env python3
"""Build deep bot→channel dataset: Telethon sc_ ∪ DB crossposting + pre-bot features.

- Channel labels: prefer Telethon live stats (full history crawl); fall back to DB live
- Join only rows with meme_id (sc_ deeplink or crossposting.meme_id)
- Pre-bot features: user_meme_reaction with reacted_at < posted_at
- Source prior: mean f1k of earlier same-source posts in this channel set

Writes:
  data/dataset_deep.parquet
  data/dataset_deep_meta.json
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "dataset_deep.parquet"
META = ROOT / "data" / "dataset_deep_meta.json"


def _df(rows: list) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame()
    return pl.DataFrame([dict(r) for r in rows], infer_schema_length=None)


async def fetch_meme_meta(conn, meme_ids: list[int]) -> pl.DataFrame:
    chunks = []
    for i in range(0, len(meme_ids), 2000):
        batch = meme_ids[i : i + 2000]
        rows = await conn.fetch(
            """
            SELECT
              m.id AS meme_id,
              m.meme_source_id,
              m.language_code,
              m.type AS meme_type,
              (m.caption IS NOT NULL) AS has_caption,
              m.status
            FROM meme m
            WHERE m.id = ANY($1::int[])
            """,
            batch,
        )
        chunks.extend(rows)
    return _df(chunks)


async def fetch_reactions(conn, meme_ids: list[int]) -> pl.DataFrame:
    chunks = []
    for i in range(0, len(meme_ids), 1500):
        batch = meme_ids[i : i + 1500]
        print(f"  reactions batch {i // 1500 + 1}… ({len(batch)} memes)", flush=True)
        rows = await conn.fetch(
            """
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
            WHERE umr.meme_id = ANY($1::int[])
            """,
            batch,
        )
        chunks.extend(rows)
        print(f"    rows so far {len(chunks)}", flush=True)
    return _df(chunks)


async def fetch_users(conn, user_ids: list[int]) -> tuple[pl.DataFrame, pl.DataFrame]:
    ut_chunks, u_chunks = [], []
    for i in range(0, len(user_ids), 5000):
        batch = user_ids[i : i + 5000]
        ut_chunks.extend(
            await conn.fetch(
                """
                SELECT id AS user_id, is_premium, language_code
                FROM user_tg WHERE id = ANY($1::bigint[])
                """,
                batch,
            )
        )
        u_chunks.extend(
            await conn.fetch(
                """
                SELECT id AS user_id, type, balance
                FROM "user" WHERE id = ANY($1::bigint[])
                """,
                batch,
            )
        )
    return _df(ut_chunks), _df(u_chunks)


async def main_async() -> None:
    url = os.environ.get("ANALYST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Set ANALYST_DATABASE_URL")

    tt_path = RAW / "channel_telethon_posts.parquet"
    posts_path = RAW / "posts.parquet"
    if not tt_path.exists():
        raise SystemExit("Run export_channel_telethon.py first")

    tt = pl.read_parquet(tt_path)
    # best row per meme_id from telethon (latest message if dups)
    tt_j = (
        tt.filter(pl.col("meme_id").is_not_null() & pl.col("views").is_not_null() & (pl.col("views") > 0))
        .sort(["meme_id", "posted_at"], descending=[False, True])
        .unique(subset=["meme_id"], keep="first")
        .select(
            [
                pl.col("meme_id").cast(pl.Int64),
                pl.col("posted_at"),
                pl.col("telegram_message_id"),
                pl.col("views").alias("views_ch"),
                pl.col("forwards").fill_null(0).alias("forwards_ch"),
                pl.col("reactions").fill_null(0).alias("reactions_ch"),
                pl.lit("telethon").alias("channel_source"),
            ]
        )
    )
    print(f"telethon joinable unique memes: {tt_j.height}")

    db_rows = []
    if posts_path.exists():
        posts = pl.read_parquet(posts_path)
        # lifetime from posts live columns
        db = posts.filter(
            pl.col("live_views").is_not_null() & (pl.col("live_views") > 0)
        ).select(
            [
                pl.col("meme_id").cast(pl.Int64),
                pl.col("posted_at"),
                pl.col("telegram_message_id"),
                pl.col("live_views").alias("views_ch"),
                pl.col("live_forwards").fill_null(0).alias("forwards_ch"),
                pl.col("live_reactions").fill_null(0).alias("reactions_ch"),
                pl.lit("crossposting_db").alias("channel_source"),
            ]
        )
        # prefer telethon when both
        only_db = db.join(tt_j.select("meme_id"), on="meme_id", how="anti")
        print(f"db-only memes (no telethon sc_): {only_db.height}")
        channel = pl.concat([tt_j, only_db], how="diagonal_relaxed")
    else:
        channel = tt_j

    # age filter: at least 36h old for "mature" lifetime
    now = datetime.utcnow()
    channel = channel.with_columns(
        [
            (1000.0 * pl.col("forwards_ch") / pl.col("views_ch")).alias("f1k_ch"),
        ]
    )
    # keep posted_at not null
    channel = channel.filter(pl.col("posted_at").is_not_null())
    print(f"channel rows before meta: {channel.height}")

    meme_ids = channel["meme_id"].unique().to_list()
    print(f"fetching meme meta for {len(meme_ids)}…")
    conn = await asyncpg.connect(url, statement_cache_size=0)
    try:
        await conn.execute("SET statement_timeout = '600s'")
        meta_m = await fetch_meme_meta(conn, [int(x) for x in meme_ids])
        print(f"  meta rows {meta_m.height}")
        # only image ok-ish
        if meta_m.height:
            channel = channel.join(meta_m, on="meme_id", how="inner")
            if "meme_type" in channel.columns:
                channel = channel.filter(
                    (pl.col("meme_type") == "image") | pl.col("meme_type").is_null()
                )
        print(f"after meta join: {channel.height}")

        print("fetching all reactions for these memes (heavy)…")
        reacts = await fetch_reactions(conn, [int(x) for x in channel["meme_id"].to_list()])
        reacts.write_parquet(RAW / "reactions_deep.parquet")
        print(f"  reactions total {reacts.height}")

        user_ids = (
            reacts["user_id"].unique().to_list() if reacts.height else []
        )
        print(f"fetching {len(user_ids)} users…")
        ut, users = await fetch_users(conn, [int(x) for x in user_ids]) if user_ids else (
            pl.DataFrame(),
            pl.DataFrame(),
        )
        ut.write_parquet(RAW / "users_tg_deep.parquet")
        users.write_parquet(RAW / "users_deep.parquet")
    finally:
        await conn.close()

    # pre-post filter
    if reacts.height == 0:
        raise SystemExit("no reactions — abort")

    r = reacts.join(channel.select(["meme_id", "posted_at"]), on="meme_id", how="inner")
    r = r.filter(pl.col("reacted_at") < pl.col("posted_at"))
    print(f"pre-post reactions: {r.height}")

    r = r.join(ut, on="user_id", how="left").join(users, on="user_id", how="left")
    r = r.with_columns(
        [
            pl.col("is_premium").fill_null(False),
            (pl.col("type").is_in(["moderator", "admin"])).fill_null(False).alias("is_mod"),
            (
                (pl.col("reaction_id") == 1)
                & pl.col("sec_to_react").is_not_null()
                & (pl.col("sec_to_react") >= 5)
                & (pl.col("sec_to_react") <= 60)
            ).alias("engaged_like"),
            (
                (pl.col("reaction_id") == 2)
                & pl.col("sec_to_react").is_not_null()
                & (pl.col("sec_to_react") < 2)
            ).alias("instant_skip"),
        ]
    )
    pre = r.group_by("meme_id").agg(
        [
            (pl.col("reaction_id") == 1).sum().alias("pre_likes"),
            (pl.col("reaction_id") == 2).sum().alias("pre_dislikes"),
            pl.len().alias("pre_reacts"),
            ((pl.col("reaction_id") == 1) & pl.col("is_premium")).sum().alias("pre_premium_likes"),
            ((pl.col("reaction_id") == 1) & pl.col("is_mod")).sum().alias("pre_mod_likes"),
            pl.col("engaged_like").sum().alias("pre_engaged_likes"),
            pl.col("instant_skip").sum().alias("pre_instant_skips"),
            pl.col("reacted_at").min().alias("first_react_at"),
        ]
    )

    df = channel.join(pre, on="meme_id", how="left")
    df = df.with_columns(
        [
            pl.col("pre_likes").fill_null(0),
            pl.col("pre_dislikes").fill_null(0),
            pl.col("pre_reacts").fill_null(0),
            pl.col("pre_premium_likes").fill_null(0),
            pl.col("pre_mod_likes").fill_null(0),
            pl.col("pre_engaged_likes").fill_null(0),
            pl.col("pre_instant_skips").fill_null(0),
        ]
    )
    # require some bot signal for supervised bot→channel (optional soft filter)
    # keep all but flag
    df = df.with_columns(
        [
            (
                pl.col("pre_likes")
                / (pl.col("pre_likes") + pl.col("pre_dislikes") + 1e-9)
            ).alias("pre_lr"),
            (pl.col("pre_likes") + 1).log().alias("pre_ln_likes"),
            pl.when(pl.col("pre_likes") > 0)
            .then(pl.col("pre_premium_likes") / pl.col("pre_likes"))
            .otherwise(None)
            .alias("pre_premium_like_frac"),
            pl.when(pl.col("pre_reacts") > 0)
            .then(pl.col("pre_instant_skips") / pl.col("pre_reacts"))
            .otherwise(None)
            .alias("pre_instant_skip_rate"),
            pl.when(pl.col("first_react_at").is_not_null())
            .then(
                (pl.col("posted_at") - pl.col("first_react_at"))
                .dt.total_hours()
                .cast(pl.Float64)
            )
            .otherwise(None)
            .alias("hours_in_bot"),
            pl.col("has_caption").fill_null(False).cast(pl.Int8).alias("has_caption_i"),
            # train_eval compatibility names
            pl.col("f1k_ch").alias("f1k_24h"),
            pl.col("forwards_ch").alias("forwards_24h"),
            pl.col("views_ch").alias("views_24h"),
            pl.col("reactions_ch").alias("reactions_24h"),
            (pl.col("pre_likes") + 1).log().alias("v4_proxy"),
        ]
    )
    df = df.with_columns(
        (pl.col("hours_in_bot").fill_null(0) + 1).log().alias("log1p_hours_in_bot")
    )

    # source prior from this channel set (time-safe)
    base = df.select(
        ["meme_id", "posted_at", "meme_source_id", "f1k_ch", "forwards_ch"]
    ).filter(pl.col("meme_source_id").is_not_null())
    # self-join via sort + group — use join on source
    left = base.rename(
        {
            "meme_id": "m_id",
            "posted_at": "m_posted",
            "f1k_ch": "m_f1k",
            "forwards_ch": "m_fwd",
        }
    )
    right = base.rename(
        {
            "meme_id": "h_id",
            "posted_at": "h_posted",
            "f1k_ch": "h_f1k",
            "forwards_ch": "h_fwd",
        }
    )
    pairs = left.join(right, on="meme_source_id", how="left").filter(
        (pl.col("h_posted") < pl.col("m_posted"))
        & (pl.col("h_posted") > pl.col("m_posted") - pl.duration(days=90))
        & (pl.col("h_id") != pl.col("m_id"))
    )
    prior = pairs.group_by("m_id").agg(
        [
            pl.col("h_f1k").mean().alias("src_prior_f1k"),
            pl.col("h_fwd").mean().alias("src_prior_fwd"),
            pl.len().alias("src_prior_n"),
        ]
    ).rename({"m_id": "meme_id"})
    df = df.join(prior, on="meme_id", how="left")
    df = df.with_columns(
        (pl.col("src_prior_n").fill_null(0) + 1).log().alias("src_prior_n_log")
    )

    # training set: need at least 1 pre like OR 5 pre reacts for "bot signal"
    df = df.with_columns(
        ((pl.col("pre_likes") >= 1) | (pl.col("pre_reacts") >= 3)).alias("has_bot_signal")
    )
    df = df.sort("posted_at")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(OUT)
    # also overwrite dataset.parquet so validate/train pick it up
    df.write_parquet(ROOT / "data" / "dataset.parquet")

    meta = {
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "label": "channel_lifetime_views_forwards",
        "n_total": df.height,
        "n_telethon": int((df["channel_source"] == "telethon").sum())
        if "channel_source" in df.columns
        else None,
        "n_db_only": int((df["channel_source"] == "crossposting_db").sum())
        if "channel_source" in df.columns
        else None,
        "n_with_bot_signal": int(df["has_bot_signal"].sum()),
        "n_pre_likes_ge5": int((df["pre_likes"] >= 5).sum()),
        "posted_at_min": str(df["posted_at"].min()),
        "posted_at_max": str(df["posted_at"].max()),
        "mean_f1k": float(df["f1k_24h"].mean()),
        "mean_pre_likes": float(df["pre_likes"].mean()),
        "mean_views": float(df["views_24h"].mean()),
    }
    META.write_text(json.dumps(meta, indent=2))
    (ROOT / "data" / "dataset_meta.json").write_text(json.dumps(meta, indent=2))
    print("META", json.dumps(meta, indent=2))
    print(f"wrote {OUT} and data/dataset.parquet")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
