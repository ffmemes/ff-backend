#!/usr/bin/env python3
"""Local Polars EDA (correlations, residuals) → reports/eda-local.md"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent
DS = ROOT / "data" / "dataset.parquet"
OUT = ROOT / "reports" / "eda-local.md"

FEATS = [
    "pre_ln_likes",
    "pre_lr",
    "pre_likes",
    "pre_reacts",
    "pre_engaged_likes",
    "pre_premium_like_frac",
    "src_prior_f1k",
    "src_prior_n",
    "log1p_hours_in_bot",
    "v4_proxy",
]


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 10:
        return float("nan")
    xr = x[mask].argsort().argsort().astype(float)
    yr = y[mask].argsort().argsort().astype(float)
    return float(np.corrcoef(xr, yr)[0, 1])


def main() -> None:
    df = pl.read_parquet(DS)
    y_f1k = df["f1k_24h"].to_numpy().astype(float)
    y_fwd = df["forwards_24h"].to_numpy().astype(float)
    src = df["src_prior_f1k"].to_numpy().astype(float)
    resid = y_f1k - src

    lines = [
        f"# Local EDA — bot→channel",
        f"",
        f"**Built:** {datetime.now(timezone.utc).isoformat()}",
        f"**n:** {df.height}",
        f"**posted_at:** {df['posted_at'].min()} → {df['posted_at'].max()}",
        f"",
        f"## Correlations (Spearman)",
        f"",
        f"| feature | vs f1k | vs forwards | vs resid_f1k |",
        f"|---------|-------:|------------:|-------------:|",
    ]
    for f in FEATS:
        if f not in df.columns:
            continue
        x = df[f].to_numpy().astype(float)
        lines.append(
            f"| `{f}` | {spearman(x, y_f1k):.3f} | {spearman(x, y_fwd):.3f} | {spearman(x, resid):.3f} |"
        )

    # saturation bands by pre_likes
    lines += ["", "## Saturation bands (pre_likes)", ""]
    q = df.with_columns(pl.col("pre_likes").qcut(5, labels=["1", "2", "3", "4", "5"]).alias("band"))
    # qcut may fail on ties — fallback ntile-like
    try:
        summary = q.group_by("band").agg(
            [
                pl.len().alias("n"),
                pl.col("pre_likes").mean().alias("avg_likes"),
                pl.col("f1k_24h").mean().alias("avg_f1k"),
                pl.col("forwards_24h").mean().alias("avg_fwd"),
            ]
        ).sort("band")
        lines.append("| band | n | avg_likes | avg_f1k | avg_fwd |")
        lines.append("|------|--:|----------:|--------:|--------:|")
        for row in summary.iter_rows(named=True):
            lines.append(
                f"| {row['band']} | {row['n']} | {row['avg_likes']:.1f} | {row['avg_f1k']:.2f} | {row['avg_fwd']:.2f} |"
            )
    except Exception as e:
        lines.append(f"(qcut failed: {e}; skip bands)")

    lines += [
        "",
        "## Missingness",
        "",
    ]
    for f in FEATS + ["src_prior_f1k", "pre_premium_like_frac"]:
        if f not in df.columns:
            continue
        null_pct = df[f].null_count() / max(df.height, 1) * 100
        lines.append(f"- `{f}`: {null_pct:.1f}% null")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
