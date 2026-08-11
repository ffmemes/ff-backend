#!/usr/bin/env python3
"""Polars: raw layers → meme-level dataset.parquet (leakage-safe priors).

Label modes:
  --label-mode 24h       strict 18–36h snapshots (smaller n, cleaner target)
  --label-mode lifetime  live views/forwards on crossposting (much larger n)
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "dataset.parquet"
META = ROOT / "data" / "dataset_meta.json"


def _load_labels(mode: str) -> pl.DataFrame:
    if mode == "24h":
        labels = pl.read_parquet(RAW / "labels_24h.parquet")
        # already has views_24h, forwards_24h, f1k_24h
        return labels
    if mode == "lifetime":
        path = RAW / "labels_lifetime.parquet"
        if not path.exists():
            raise SystemExit(
                "labels_lifetime.parquet missing — re-run export_raw.py "
                "(updated script writes this file)"
            )
        labels = pl.read_parquet(path)
        # normalize column names so train_eval keeps working
        return labels.rename(
            {
                "views_life": "views_24h",
                "forwards_life": "forwards_24h",
                "reactions_life": "reactions_24h",
                "comments_life": "comments_24h",
                "f1k_life": "f1k_24h",
            }
        )
    raise SystemExit(f"unknown label mode: {mode}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--label-mode",
        choices=("24h", "lifetime"),
        default="lifetime",
        help="24h=strict snaps; lifetime=all posts with live channel stats (default)",
    )
    args = ap.parse_args()

    posts = pl.read_parquet(RAW / "posts.parquet")
    labels = _load_labels(args.label_mode)
    reacts = pl.read_parquet(RAW / "reactions_pre.parquet")
    ut = pl.read_parquet(RAW / "users_tg.parquet")
    users = pl.read_parquet(RAW / "users.parquet")
    hist = pl.read_parquet(RAW / "channel_history.parquet")
    mss = pl.read_parquet(RAW / "meme_source_stats.parquet")

    # join premium / type onto reactions
    if reacts.height:
        r = reacts.join(ut, on="user_id", how="left").join(users, on="user_id", how="left")
        r = r.with_columns(
            [
                pl.col("is_premium").fill_null(False),
                (pl.col("type").is_in(["moderator", "admin"])).alias("is_mod"),
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
    else:
        pre = pl.DataFrame(
            schema={
                "meme_id": pl.Int64,
                "pre_likes": pl.UInt32,
                "pre_dislikes": pl.UInt32,
                "pre_reacts": pl.UInt32,
                "pre_premium_likes": pl.UInt32,
                "pre_mod_likes": pl.UInt32,
                "pre_engaged_likes": pl.UInt32,
                "pre_instant_skips": pl.UInt32,
                "first_react_at": pl.Datetime,
            }
        )

    # dataset = labeled posts only
    df = labels.join(
        posts.select(
            [
                "meme_id",
                "score_version",
                "has_caption",
                "language_code",
                "meme_source_id",
            ]
        ),
        on="meme_id",
        how="left",
    ).join(pre, on="meme_id", how="left")

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

    df = df.with_columns(
        [
            (pl.col("pre_likes") / (pl.col("pre_likes") + pl.col("pre_dislikes") + 1e-9)).alias(
                "pre_lr"
            ),
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
                (pl.col("posted_at") - pl.col("first_react_at")).dt.total_hours().cast(pl.Float64)
            )
            .otherwise(None)
            .alias("hours_in_bot"),
            pl.col("has_caption").fill_null(False).cast(pl.Int8).alias("has_caption_i"),
        ]
    )
    df = df.with_columns(
        [
            (pl.col("hours_in_bot").fill_null(0) + 1).log().alias("log1p_hours_in_bot"),
            pl.col("pre_ln_likes").alias("v4_proxy"),
        ]
    )

    # source prior from channel history (time-safe)
    # for each labeled row: mean f1k of hist same source, posted_at < this, within 90d
    h = hist.select(
        [
            pl.col("meme_id").alias("h_meme_id"),
            pl.col("posted_at").alias("h_posted_at"),
            pl.col("meme_source_id").alias("h_source_id"),
            pl.col("f1k").alias("h_f1k"),
            pl.col("forwards").alias("h_fwd"),
        ]
    )

    # Join all history pairs then filter — OK for ~1–2k × sources
    labeled_src = df.select(["meme_id", "posted_at", "meme_source_id", "f1k_24h"])
    pairs = labeled_src.join(
        h,
        left_on="meme_source_id",
        right_on="h_source_id",
        how="left",
    ).filter(
        (pl.col("h_posted_at") < pl.col("posted_at"))
        & (pl.col("h_posted_at") > pl.col("posted_at") - pl.duration(days=90))
        & (pl.col("h_meme_id") != pl.col("meme_id"))
    )
    prior = pairs.group_by("meme_id").agg(
        [
            pl.col("h_f1k").mean().alias("src_prior_f1k"),
            pl.col("h_fwd").mean().alias("src_prior_fwd"),
            pl.len().alias("src_prior_n"),
        ]
    )
    df = df.join(prior, on="meme_id", how="left")
    df = df.with_columns(
        [
            (pl.col("src_prior_n").fill_null(0) + 1).log().alias("src_prior_n_log"),
        ]
    )

    # bot source stats (point-in-time weak leakage — optional features)
    if mss.height:
        df = df.join(
            mss.select(
                [
                    "meme_source_id",
                    pl.col("nlikes").alias("src_bot_nlikes"),
                    pl.col("nmemes_sent").alias("src_bot_nmemes_sent"),
                ]
            ),
            on="meme_source_id",
            how="left",
        )

    df = df.sort("posted_at")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(OUT)

    meta = {
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "label_mode": args.label_mode,
        "n": df.height,
        "posted_at_min": str(df["posted_at"].min()),
        "posted_at_max": str(df["posted_at"].max()),
        "columns": df.columns,
        "features_v1": [
            "pre_ln_likes",
            "pre_lr",
            "pre_reacts",
            "pre_engaged_likes",
            "pre_premium_like_frac",
            "pre_premium_likes",
            "src_prior_f1k",
            "src_prior_n_log",
            "has_caption_i",
            "log1p_hours_in_bot",
        ],
        "baselines": ["v4_proxy", "src_prior_f1k"],
        "labels": ["f1k_24h", "forwards_24h", "views_24h", "reactions_24h"],
        "label_note": (
            "column names always f1k_24h/… for train_eval; "
            "when label_mode=lifetime they are live channel stats, not 18–36h snaps"
        ),
    }
    META.write_text(json.dumps(meta, indent=2))
    print(f"wrote {OUT} n={df.height} label_mode={args.label_mode}")
    print(f"pre_likes mean={df['pre_likes'].mean():.1f} f1k mean={df['f1k_24h'].mean():.2f}")


if __name__ == "__main__":
    main()
