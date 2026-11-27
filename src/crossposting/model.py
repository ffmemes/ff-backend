"""Crosspost model as data: ridge on decision-time features, scored without numpy.

``ridge_dl`` (offline walk-forward 2026-11-27): 11 features of one candidate, target
zf_24h = ln(1 + forwards at the snapshot nearest +24h) - mean over the channel's MSK week.
The nightly flow (src/flows/crossposting/model_loop.py) fits it on every labeled decision and
writes a ``crossposting_model`` row; posting loads the active row with ``load_model``.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

FEATURES = (
    "ln_likes",
    "lr",
    "react_rate",
    "log_sent",
    "src_prior_z",
    "log_src_prior_n",
    "src_views_pct",
    "src_views_missing",
    "has_caption",
    "is_upload",
    "log_meme_age",
)
# Attached by service._attach_model_inputs; absent when that query failed.
MODEL_INPUTS = ("is_upload", "src_views_pct", "src_prior_z", "src_prior_n")
ALPHA = 10.0
PRIOR_K = 5.0  # source prior = sum(zf) / (n + PRIOR_K)
MSK = timedelta(hours=3)


def features(r: dict[str, Any]) -> dict[str, float] | None:
    """ridge_dl features of one pool row; None when an input is missing."""
    if any(k not in r for k in MODEL_INPUTS) or None in (
        r.get("nlikes"),
        r.get("ndislikes"),
        r.get("nmemes_sent"),
        r["src_prior_z"],
        r["src_prior_n"],
    ):
        return None
    likes, dislikes, sent, pct = r["nlikes"], r["ndislikes"], r["nmemes_sent"], r["src_views_pct"]
    return {
        "ln_likes": math.log1p(likes),
        "lr": (likes + 1) / (likes + dislikes + 1),
        "react_rate": (likes + dislikes) / max(sent, 1),
        "log_sent": math.log1p(sent),
        "src_prior_z": float(r["src_prior_z"]),
        "log_src_prior_n": math.log1p(r["src_prior_n"]),
        "src_views_pct": 0.5 if pct is None else float(pct),
        "src_views_missing": float(pct is None),
        "has_caption": float(bool(r.get("has_caption"))),
        "is_upload": float(bool(r["is_upload"])),
        "log_meme_age": math.log1p(max(r.get("age_days") or 0, 0)),
    }


@dataclass
class Model:
    version: int
    features: list[str]
    coefs: list[float]
    mean: list[float]
    scale: list[float]
    intercept: float

    def predict(self, x: dict[str, float]) -> float:
        """Predicted zf_24h."""
        terms = zip(self.features, self.coefs, self.mean, self.scale, strict=True)
        return self.intercept + sum(c * (x[f] - m) / s for f, c, m, s in terms)


def load_model(row: dict[str, Any]) -> Model:
    """Validate a crossposting_model row; ValueError/TypeError when it cannot score safely."""
    feats = list(row["features"])
    if not feats or len(set(feats)) != len(feats) or set(feats) - set(FEATURES):
        raise ValueError(f"unknown or duplicate model features: {feats}")
    coefs, mean, scale = ([float(v) for v in row[k]] for k in ("coefs", "mean", "scale"))
    if not len(coefs) == len(mean) == len(scale) == len(feats):
        raise ValueError("coefs/mean/scale do not match features")
    intercept = float(row["intercept"])
    if not all(map(math.isfinite, [*coefs, *mean, *scale, intercept])) or min(scale) <= 0:
        raise ValueError("non-finite coefficient or non-positive scale")
    return Model(int(row["version"]), feats, coefs, mean, scale, intercept)


def fit_ridge(
    xs: list[dict[str, float]],
    y: list[float],
    features: list[str] | tuple[str, ...] = FEATURES,
    alpha: float = ALPHA,
) -> dict[str, Any]:
    """Ridge on standardized ``features`` (= sklearn StandardScaler + Ridge(alpha)), closed form."""
    n, p = len(xs), len(features)
    cols = [[x[f] for x in xs] for f in features]
    mean = [sum(c) / n for c in cols]
    scale = [math.sqrt(sum((v - m) ** 2 for v in c) / n) or 1.0 for c, m in zip(cols, mean)]
    z = [[(v - m) / s for v in c] for c, m, s in zip(cols, mean, scale)]
    ybar = sum(y) / n
    yc = [t - ybar for t in y]
    a = [
        [sum(map(math.prod, zip(z[i], z[j]))) + alpha * (i == j) for j in range(p)]
        for i in range(p)
    ]
    b = [sum(map(math.prod, zip(z[i], yc))) for i in range(p)]
    return {
        "features": list(features),
        "coefs": _solve(a, b),
        "mean": mean,
        "scale": scale,
        "intercept": ybar,
    }


def _sha256(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def spec_hash(features: list[str], alpha: float) -> str:
    return _sha256({"features": list(features), "alpha": float(alpha), "target": "zf_24h"})


def coefs_hash(fit: dict[str, Any]) -> str:
    return _sha256({k: fit[k] for k in ("features", "coefs", "mean", "scale", "intercept")})


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gauss-Jordan elimination; a is symmetric positive definite (ridge), so pivots are > 0."""
    m = [row[:] + [v] for row, v in zip(a, b)]
    n = len(m)
    for c in range(n):
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] for i in range(n)]


def msk_week(t: datetime) -> date:
    d = (t + MSK).date()
    return d - timedelta(days=d.weekday())


def add_zf(labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Set lf = ln(1 + f24), week and zf = lf - mean over its MSK week, in place (one channel)."""
    weeks: dict[date, list[float]] = defaultdict(list)
    for r in labels:
        r["lf"], r["week"] = math.log1p(r["f24"]), msk_week(r["posted_at"])
        weeks[r["week"]].append(r["lf"])
    mu = {w: sum(v) / len(v) for w, v in weeks.items()}
    for r in labels:
        r["zf"] = r["lf"] - mu[r["week"]]
    return labels


def source_prior(labels: list[dict[str, Any]], source_id: int, at: datetime) -> tuple[float, int]:
    """Own-channel source prior as known at ``at``: the source's posts 48h-180d before it, zf
    against week means of posts matured by then only (later posts, the target included, never
    count); sum(zf) / (n + 5). labels: add_zf output."""
    past = [r for r in labels if r["posted_at"] < at - timedelta(hours=48)]
    weeks: dict[date, list[float]] = defaultdict(list)
    for r in past:
        weeks[r["week"]].append(r["lf"])
    lo = at - timedelta(days=180)
    zs = [
        r["lf"] - sum(weeks[r["week"]]) / len(weeks[r["week"]])
        for r in past
        if r["source_id"] == source_id and r["posted_at"] >= lo
    ]
    return sum(zs) / (len(zs) + PRIOR_K), len(zs)


def _ranks(v: list[float]) -> list[float]:
    order = sorted(range(len(v)), key=v.__getitem__)
    out = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for k in order[i : j + 1]:
            out[k] = (i + j) / 2
        i = j + 1
    return out


def spearman(a: list[float], b: list[float]) -> float:
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return cov / den if den else 0.0


def _week_pct(rows: list[dict[str, Any]], key: str) -> list[float]:
    """Percentile of rows[key] within each row's MSK week."""
    by_week: dict[date, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        by_week[msk_week(r["posted_at"])].append(i)
    out = [0.0] * len(rows)
    for idx in by_week.values():
        for i, rank in zip(idx, _ranks([float(rows[i][key]) for i in idx])):
            out[i] = (rank + 0.5) / len(idx)
    return out


def walk_forward(
    rows: list[dict[str, Any]],
    features: list[str] | tuple[str, ...] = FEATURES,
    alpha: float = ALPHA,
    min_train: int = 150,
) -> list[dict[str, Any]]:
    """Out-of-sample predictions on published posts: each MSK week is ranked by a fit on posts
    whose label matured before it. rows: {posted_at, x, zf, score}; returns test rows + pred."""
    by_week: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_week[msk_week(r["posted_at"])].append(r)
    out = []
    for w in sorted(by_week):
        cutoff = datetime.combine(w, time()) - MSK - timedelta(hours=36)
        train = [r for r in rows if r["posted_at"] < cutoff]
        if len(train) < min_train:
            continue
        fit = fit_ridge([r["x"] for r in train], [r["zf"] for r in train], features, alpha)
        m = Model(0, **fit)
        out += [{**r, "pred": m.predict(r["x"])} for r in by_week[w]]
    return out


def compare(test: list[dict[str, Any]], min_segment: int = 10) -> dict[str, Any]:
    """Spearman(within-week percentile, zf) of ``pred`` vs ``base`` on the same posts, overall
    and in three consecutive time segments (deltas = pred minus base)."""
    test = sorted((r for r in test if r.get("base") is not None), key=lambda r: r["posted_at"])
    if len(test) < 3 * min_segment:
        return {"n": len(test)}
    pm, pb, zf = _week_pct(test, "pred"), _week_pct(test, "base"), [r["zf"] for r in test]
    cuts = [0, len(test) // 3, 2 * len(test) // 3, len(test)]
    thirds = [
        spearman(pm[a:b], zf[a:b]) - spearman(pb[a:b], zf[a:b]) for a, b in zip(cuts, cuts[1:])
    ]
    sm, sb = spearman(pm, zf), spearman(pb, zf)
    return {
        "n": len(test),
        "since": str(test[0]["posted_at"]),
        "spearman_model": round(sm, 4),
        "spearman_base": round(sb, 4),
        "delta": round(sm - sb, 4),
        "thirds": [round(d, 4) for d in thirds],
    }
