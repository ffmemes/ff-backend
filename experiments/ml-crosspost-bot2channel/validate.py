#!/usr/bin/env python3
"""Walk-forward validation vs v4 baseline (anti-overfit).

Expanding time folds:
  fold k: train on first cut_k of rows, test on next TEST_FRAC of remaining
  cuts at 50%, 65%, 80% of sorted timeline → 3 folds with ~15% test each-ish

Pass (frozen in features.py):
  - top20 f1k lift >= v4_lift + 0.05 on >= 2 of 3 folds
  - for winning model, mean |train_spearman - test_spearman| < 0.25
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from features import (
    FEATURES,
    MIN_TEST_N,
    PASS_LIFT_DELTA_VS_V4,
    PASS_MAX_SPEARMAN_GAP,
    PASS_MIN_FOLDS,
)

ROOT = Path(__file__).resolve().parent
DS = ROOT / "data" / "dataset.parquet"
OUT = ROOT / "reports" / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-walkforward.md"

# train_end fractions of full sorted data; test = next 0.15 of full n
FOLDS = [
    (0.50, 0.15),
    (0.65, 0.15),
    (0.80, 0.15),
]


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    mask = np.isfinite(a) & np.isfinite(b)
    if mask.sum() < 10:
        return float("nan")
    ar = a[mask].argsort().argsort().astype(float)
    br = b[mask].argsort().argsort().astype(float)
    return float(np.corrcoef(ar, br)[0, 1])


def top_frac_lift(score: np.ndarray, y: np.ndarray, frac: float = 0.2) -> float:
    mask = np.isfinite(score) & np.isfinite(y)
    score, y = score[mask], y[mask]
    if len(y) < 20:
        return float("nan")
    k = max(1, int(len(y) * frac))
    idx = np.argsort(-score)[:k]
    overall = float(y.mean())
    if overall <= 0:
        return float("nan")
    return float(y[idx].mean() / overall)


def fill_X(df: pl.DataFrame, cols: list[str]) -> np.ndarray:
    cols_out = []
    for c in cols:
        if c not in df.columns:
            cols_out.append(np.zeros(df.height, dtype=float))
            continue
        x = df[c].to_numpy().astype(float)
        med = np.nanmedian(x) if np.isfinite(x).any() else 0.0
        cols_out.append(np.where(np.isfinite(x), x, med))
    return np.column_stack(cols_out)


def eval_fold(
    name: str,
    score_te: np.ndarray,
    score_tr: np.ndarray,
    y_te: np.ndarray,
    y_tr: np.ndarray,
    fwd_te: np.ndarray,
    hit_te: np.ndarray,
) -> dict:
    row = {
        "model": name,
        "spearman_te": spearman(score_te, y_te),
        "spearman_tr": spearman(score_tr, y_tr),
        "lift_f1k": top_frac_lift(score_te, y_te),
        "lift_fwd": top_frac_lift(score_te, fwd_te),
    }
    row["spearman_gap"] = row["spearman_tr"] - row["spearman_te"]
    try:
        row["auc"] = float(roc_auc_score(hit_te, score_te))
        row["ap"] = float(average_precision_score(hit_te, score_te))
    except Exception:
        row["auc"] = float("nan")
        row["ap"] = float("nan")
    return row


def main() -> None:
    df = pl.read_parquet(DS).sort("posted_at")
    # Prefer rows with real bot pre-signal (deep dataset flag if present)
    if "pre_likes" in df.columns:
        df = df.filter(pl.col("pre_likes") >= 5)
    n = df.height
    print(f"rows after pre_likes>=5 filter: {n}")
    all_rows: list[dict] = []
    fold_meta: list[dict] = []

    for fi, (train_frac, test_frac) in enumerate(FOLDS, start=1):
        tr_end = int(n * train_frac)
        te_end = min(n, tr_end + int(n * test_frac))
        train = df.slice(0, tr_end)
        test = df.slice(tr_end, te_end - tr_end)
        if test.height < MIN_TEST_N or train.height < MIN_TEST_N:
            fold_meta.append(
                {
                    "fold": fi,
                    "skip": True,
                    "reason": f"n_train={train.height} n_test={test.height}",
                }
            )
            continue

        y_tr = train["f1k_24h"].to_numpy().astype(float)
        y_te = test["f1k_24h"].to_numpy().astype(float)
        fwd_tr = train["forwards_24h"].to_numpy().astype(float)
        fwd_te = test["forwards_24h"].to_numpy().astype(float)
        p75 = float(np.nanpercentile(y_tr, 75))
        # Lifetime labels: absolute forwards≥12 is almost always true on big
        # channels — use f1k top-quartile only (rate, not volume of reach).
        hit_tr = (y_tr >= p75).astype(int)
        hit_te = (y_te >= p75).astype(int)

        X_tr = fill_X(train, FEATURES)
        X_te = fill_X(test, FEATURES)

        v4_tr = train["v4_proxy"].to_numpy().astype(float)
        v4_te = test["v4_proxy"].to_numpy().astype(float)
        src_te = test["src_prior_f1k"].to_numpy().astype(float)
        src_te = np.where(np.isfinite(src_te), src_te, np.nanmedian(src_te))
        src_tr = train["src_prior_f1k"].to_numpy().astype(float)
        src_tr = np.where(np.isfinite(src_tr), src_tr, np.nanmedian(src_tr))

        fold_meta.append(
            {
                "fold": fi,
                "skip": False,
                "n_train": train.height,
                "n_test": test.height,
                "train_end": str(train["posted_at"].max()),
                "test_start": str(test["posted_at"].min()),
                "test_end": str(test["posted_at"].max()),
                "hit_p75": p75,
                "hit_rate_te": float(hit_te.mean()),
            }
        )

        models: list[tuple[str, np.ndarray, np.ndarray]] = []
        models.append(("v4_proxy", v4_te, v4_tr))
        models.append(("src_prior_f1k", src_te, src_tr))

        ridge = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
        ridge.fit(X_tr, y_tr)
        models.append(("ridge_f1k", ridge.predict(X_te), ridge.predict(X_tr)))

        logit = make_pipeline(
            StandardScaler(),
            LogisticRegression(max_iter=500, C=0.5, class_weight="balanced"),
        )
        logit.fit(X_tr, hit_tr)
        models.append(
            (
                "logreg_hit",
                logit.predict_proba(X_te)[:, 1],
                logit.predict_proba(X_tr)[:, 1],
            )
        )

        hgb_r = HistGradientBoostingRegressor(
            max_depth=3,
            min_samples_leaf=20,
            max_iter=80,
            learning_rate=0.08,
            random_state=42,
        )
        hgb_r.fit(X_tr, y_tr)
        models.append(("hgb_reg_depth3", hgb_r.predict(X_te), hgb_r.predict(X_tr)))

        hgb_c = HistGradientBoostingClassifier(
            max_depth=3,
            min_samples_leaf=20,
            max_iter=80,
            learning_rate=0.08,
            random_state=42,
        )
        hgb_c.fit(X_tr, hit_tr)
        models.append(
            (
                "hgb_clf_depth3",
                hgb_c.predict_proba(X_te)[:, 1],
                hgb_c.predict_proba(X_tr)[:, 1],
            )
        )

        for name, ste, str_ in models:
            row = eval_fold(name, ste, str_, y_te, y_tr, fwd_te, hit_te)
            row["fold"] = fi
            all_rows.append(row)

    # Aggregate
    model_names = sorted({r["model"] for r in all_rows})
    summary = []
    for name in model_names:
        rows = [r for r in all_rows if r["model"] == name]
        lifts = [r["lift_f1k"] for r in rows if np.isfinite(r["lift_f1k"])]
        gaps = [r["spearman_gap"] for r in rows if np.isfinite(r["spearman_gap"])]
        summary.append(
            {
                "model": name,
                "n_folds": len(rows),
                "mean_lift_f1k": float(np.mean(lifts)) if lifts else float("nan"),
                "mean_auc": float(np.mean([r["auc"] for r in rows if np.isfinite(r["auc"])])),
                "mean_gap": float(np.mean(gaps)) if gaps else float("nan"),
                "lifts": lifts,
            }
        )

    v4 = next(s for s in summary if s["model"] == "v4_proxy")
    v4_lifts = v4["lifts"]

    # per-model fold wins vs v4
    verdicts = []
    for s in summary:
        if s["model"] in ("v4_proxy", "src_prior_f1k"):
            continue
        rows = [r for r in all_rows if r["model"] == s["model"]]
        wins = 0
        for r in rows:
            # same fold v4
            v4r = next(
                x for x in all_rows if x["model"] == "v4_proxy" and x["fold"] == r["fold"]
            )
            if (
                np.isfinite(r["lift_f1k"])
                and np.isfinite(v4r["lift_f1k"])
                and r["lift_f1k"] >= v4r["lift_f1k"] + PASS_LIFT_DELTA_VS_V4
            ):
                wins += 1
        gap_ok = np.isfinite(s["mean_gap"]) and s["mean_gap"] < PASS_MAX_SPEARMAN_GAP
        pass_ = wins >= PASS_MIN_FOLDS and gap_ok
        verdicts.append(
            {
                "model": s["model"],
                "wins_vs_v4": wins,
                "n_folds": s["n_folds"],
                "mean_lift": s["mean_lift_f1k"],
                "mean_v4_lift": float(np.mean(v4_lifts)) if v4_lifts else float("nan"),
                "mean_gap": s["mean_gap"],
                "gap_ok": gap_ok,
                "PASS": pass_,
            }
        )

    any_pass = any(v["PASS"] for v in verdicts)
    best = (
        max(verdicts, key=lambda v: (v["wins_vs_v4"], v["mean_lift"]))
        if verdicts
        else None
    )

    lines = [
        f"# Walk-forward validation — {datetime.now(timezone.utc).date()}",
        "",
        f"- n_total={n}",
        f"- features={FEATURES}",
        f"- pass bar: lift ≥ v4+{PASS_LIFT_DELTA_VS_V4} on ≥{PASS_MIN_FOLDS}/3 folds; "
        f"mean spearman gap < {PASS_MAX_SPEARMAN_GAP}",
        "",
        "## Folds",
        "",
        "| fold | n_train | n_test | train_end | test window | hit_p75 | hit_rate_te |",
        "|-----:|--------:|-------:|-----------|-------------|--------:|------------:|",
    ]
    for m in fold_meta:
        if m.get("skip"):
            lines.append(f"| {m['fold']} | skip | | | {m.get('reason','')} | | |")
            continue
        lines.append(
            f"| {m['fold']} | {m['n_train']} | {m['n_test']} | `{m['train_end']}` | "
            f"`{m['test_start']}` → `{m['test_end']}` | {m['hit_p75']:.2f} | {m['hit_rate_te']:.3f} |"
        )

    lines += [
        "",
        "## Per-fold metrics",
        "",
        "| fold | model | lift_f1k | lift_fwd | spearman_te | spearman_gap | AUC | AP |",
        "|-----:|-------|---------:|---------:|------------:|-------------:|----:|---:|",
    ]
    for r in sorted(all_rows, key=lambda x: (x["fold"], x["model"])):
        lines.append(
            f"| {r['fold']} | {r['model']} | {r['lift_f1k']:.3f} | {r['lift_fwd']:.3f} | "
            f"{r['spearman_te']:.3f} | {r['spearman_gap']:.3f} | {r['auc']:.3f} | {r['ap']:.3f} |"
        )

    lines += [
        "",
        "## Aggregate vs pass bar",
        "",
        "| model | wins vs v4 | mean lift f1k | mean v4 lift | mean spearman gap | gap_ok | PASS |",
        "|-------|-----------:|--------------:|-------------:|------------------:|:------:|:----:|",
    ]
    for v in verdicts:
        lines.append(
            f"| {v['model']} | {v['wins_vs_v4']}/{v['n_folds']} | {v['mean_lift']:.3f} | "
            f"{v['mean_v4_lift']:.3f} | {v['mean_gap']:.3f} | {v['gap_ok']} | "
            f"{'YES' if v['PASS'] else 'no'} |"
        )
    # baselines
    lines.append(
        f"| v4_proxy | — | {v4['mean_lift_f1k']:.3f} | — | {v4['mean_gap']:.3f} | — | baseline |"
    )

    lines += [
        "",
        "## Verdict",
        "",
    ]
    if any_pass and best:
        lines.append(
            f"**PASS** — `{best['model']}` wins {best['wins_vs_v4']}/{best['n_folds']} folds "
            f"(mean lift {best['mean_lift']:.3f} vs v4 {best['mean_v4_lift']:.3f})."
        )
        lines.append("Next: optional decision_log **shadow score only** (not sole ranker).")
    else:
        lines.append(
            "**HOLD / FAIL walk-forward** — no model clears lift vs v4 on ≥2 folds "
            "with overfit guard."
        )
        if best:
            lines.append(
                f"Closest: `{best['model']}` wins {best['wins_vs_v4']}/{best['n_folds']}, "
                f"mean lift {best['mean_lift']:.3f} (v4 {best['mean_v4_lift']:.3f}), "
                f"gap={best['mean_gap']:.3f}."
            )
        lines.append("Keep production v4; do not ship linear/logreg/HGB.")
    lines.append("")
    lines.append("Single 70/30 split can look better than walk-forward — trust this report more.")
    lines.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines))
    print("\n".join(lines))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
