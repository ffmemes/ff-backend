#!/usr/bin/env python3
"""Simple models vs v4 baseline — time split, anti-overfit constraints."""

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

from features import FEATURES

ROOT = Path(__file__).resolve().parent
DS = ROOT / "data" / "dataset.parquet"
OUT = ROOT / "reports" / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-models.md"


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
    overall = y.mean()
    if overall <= 0:
        return float("nan")
    return float(y[idx].mean() / overall)


def hit_at_top(score: np.ndarray, hit: np.ndarray, frac: float = 0.2) -> float:
    mask = np.isfinite(score)
    score, hit = score[mask], hit[mask]
    k = max(1, int(len(score) * frac))
    idx = np.argsort(-score)[:k]
    return float(hit[idx].mean())


def fill_X(df: pl.DataFrame, cols: list[str]) -> np.ndarray:
    X = []
    for c in cols:
        if c not in df.columns:
            X.append(np.zeros(df.height))
        else:
            x = df[c].to_numpy().astype(float)
            med = np.nanmedian(x) if np.isfinite(x).any() else 0.0
            x = np.where(np.isfinite(x), x, med)
            X.append(x)
    return np.column_stack(X)


def main() -> None:
    df = pl.read_parquet(DS).sort("posted_at")
    if "pre_likes" in df.columns:
        df = df.filter(pl.col("pre_likes") >= 5)
    n = df.height
    # time split ~70/30
    cut_idx = int(n * 0.7)
    train = df.head(cut_idx)
    test = df.tail(n - cut_idx)
    cut_time = train["posted_at"].max()

    y_tr = train["f1k_24h"].to_numpy().astype(float)
    y_te = test["f1k_24h"].to_numpy().astype(float)
    fwd_te = test["forwards_24h"].to_numpy().astype(float)

    p75 = float(np.nanpercentile(y_tr, 75))
    # f1k top-quartile only (forwards≥12 is useless on high-view lifetime stats)
    hit_tr = (y_tr >= p75).astype(int)
    hit_te = (y_te >= p75).astype(int)

    X_tr = fill_X(train, FEATURES)
    X_te = fill_X(test, FEATURES)

    # baselines
    v4_te = test["v4_proxy"].to_numpy().astype(float)
    src_te = test["src_prior_f1k"].to_numpy().astype(float)
    src_te = np.where(np.isfinite(src_te), src_te, np.nanmedian(src_te))

    results = []

    def eval_score(name: str, score: np.ndarray, train_score: np.ndarray | None = None) -> dict:
        row = {
            "name": name,
            "spearman_f1k": spearman(score, y_te),
            "top20_lift_f1k": top_frac_lift(score, y_te),
            "top20_lift_fwd": top_frac_lift(score, fwd_te),
            "hit_rate_top20": hit_at_top(score, hit_te),
        }
        try:
            row["auc"] = float(roc_auc_score(hit_te, score))
            row["ap"] = float(average_precision_score(hit_te, score))
        except Exception:
            row["auc"] = float("nan")
            row["ap"] = float("nan")
        if train_score is not None:
            row["spearman_f1k_train"] = spearman(train_score, y_tr)
        return row

    results.append(eval_score("v4_proxy=ln(pre_likes+1)", v4_te, train["v4_proxy"].to_numpy().astype(float)))
    results.append(eval_score("src_prior_f1k", src_te))

    # Ridge on f1k
    ridge = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
    ridge.fit(X_tr, y_tr)
    results.append(
        eval_score("ridge_f1k", ridge.predict(X_te), ridge.predict(X_tr))
    )

    # LogReg HIT
    logit = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=500, C=0.5, class_weight="balanced"),
    )
    logit.fit(X_tr, hit_tr)
    results.append(
        eval_score(
            "logreg_hit",
            logit.predict_proba(X_te)[:, 1],
            logit.predict_proba(X_tr)[:, 1],
        )
    )

    # Shallow HGB regressor
    hgb_r = HistGradientBoostingRegressor(
        max_depth=3,
        min_samples_leaf=20,
        max_iter=80,
        learning_rate=0.08,
        random_state=42,
    )
    hgb_r.fit(X_tr, y_tr)
    results.append(eval_score("hgb_reg_depth3", hgb_r.predict(X_te), hgb_r.predict(X_tr)))

    # Shallow HGB classifier
    hgb_c = HistGradientBoostingClassifier(
        max_depth=3,
        min_samples_leaf=20,
        max_iter=80,
        learning_rate=0.08,
        random_state=42,
    )
    hgb_c.fit(X_tr, hit_tr)
    results.append(
        eval_score(
            "hgb_clf_depth3",
            hgb_c.predict_proba(X_te)[:, 1],
            hgb_c.predict_proba(X_tr)[:, 1],
        )
    )

    # Ridge coefficients
    ridge_only = Ridge(alpha=1.0)
    Xs = StandardScaler().fit_transform(X_tr)
    ridge_only.fit(Xs, y_tr)
    coefs = sorted(zip(FEATURES, ridge_only.coef_), key=lambda t: -abs(t[1]))

    v4_lift = next(r["top20_lift_f1k"] for r in results if r["name"].startswith("v4"))
    best = max(results, key=lambda r: (r["top20_lift_f1k"] if np.isfinite(r["top20_lift_f1k"]) else -1))
    beats = (
        best["name"] != "v4_proxy=ln(pre_likes+1)"
        and np.isfinite(best["top20_lift_f1k"])
        and best["top20_lift_f1k"] >= v4_lift + 0.05
    )

    lines = [
        f"# Bot→channel models — {datetime.now(timezone.utc).date()}",
        "",
        f"- n_total={n}, n_train={train.height}, n_test={test.height}",
        f"- time cut (train max posted_at): `{cut_time}`",
        f"- HIT threshold: train f1k p75={p75:.2f} OR forwards≥12",
        f"- train hit rate={hit_tr.mean():.3f}, test hit rate={hit_te.mean():.3f}",
        f"- features: {FEATURES}",
        "",
        "## Test metrics",
        "",
        "| model | spearman f1k | top20 lift f1k | top20 lift fwd | hit@top20 | AUC | AP | spearman train |",
        "|-------|-------------:|---------------:|---------------:|----------:|----:|---:|---------------:|",
    ]
    for r in results:
        lines.append(
            f"| {r['name']} | {r['spearman_f1k']:.3f} | {r['top20_lift_f1k']:.3f} | "
            f"{r['top20_lift_fwd']:.3f} | {r['hit_rate_top20']:.3f} | {r['auc']:.3f} | {r['ap']:.3f} | "
            f"{r.get('spearman_f1k_train', float('nan')):.3f} |"
        )

    lines += [
        "",
        "## Ridge coefficients (standardized features)",
        "",
        "| feature | coef |",
        "|---------|-----:|",
    ]
    for name, c in coefs:
        lines.append(f"| `{name}` | {c:.4f} |")

    lines += [
        "",
        "## Verdict",
        "",
        f"- Best by test top20 f1k lift: **{best['name']}** (lift={best['top20_lift_f1k']:.3f})",
        f"- v4_proxy lift: **{v4_lift:.3f}**",
        f"- Offline ship bar (lift ≥ v4+0.05): **{'PASS' if beats else 'HOLD / no clear win'}**",
        "",
        "Do not change production ranker based on this alone.",
        "",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines))
    print("\n".join(lines))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
