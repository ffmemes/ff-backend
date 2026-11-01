"""Crosspost scoring: every live and shadow score, in one place.

A *factor* is a named number computed from one candidate row (``None`` when its
inputs are missing). A *score* is the product of named factors. Candidates are
preselected from the whole pool by ``PRESELECT`` (needs only pool columns), the
top-N get shadow inputs attached, then ``LIVE`` picks among them.

Promote a shadow score on a channel: edit ``LIVE``. Add a score: add its factors
to ``FACTORS`` and a tuple to ``SCORES`` (plus a ``SCORE_VERSION`` int).
Shadow scores are only ranked within the PRESELECT top-N.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

Row = dict[str, Any]

# impr_penalty is 0, not the intended 0.8 (RU) / 0.5 (EN): the old SQL bound it into
# `CASE ... THEN 1 ELSE :impr_penalty END`, which Postgres typed integer, so asyncpg
# sent 0. Production has always zeroed memes with raw_impr_rank > 1; kept as-is.
# The intended values live on in the quirk-fix A/B arm (v4q / v2q).
CHANNEL_PARAMS: dict[str, dict[str, Any]] = {
    "tgchannelru": {
        "impr_penalty": 0.0,
        "impr_penalty_intended": 0.8,
        "age_threshold": 7,
        "language_code": "ru",
    },
    "tgchannelen": {
        "impr_penalty": 0.0,
        "impr_penalty_intended": 0.5,
        "age_threshold": 90,
        "language_code": "en",
    },
}


def _src_quality_mult(r: Row, channel: str) -> float:
    # Mirrors the old SQL: LEAST(2, GREATEST(0.5, signal / NULLIF(median, 0))).
    # GREATEST ignores NULL, so a source without enough history scores 0.5, not 1.0.
    signal, median = r.get("src_signal"), r.get("median_signal")
    if signal is None or not median:
        return 0.5
    return max(0.5, min(2.0, float(signal) / float(median)))


def _v5_base(r: Row, channel: str) -> float | None:
    """2026-10-30 walk-forward study (experiments/2026-10-30-crosspost-v5-shadow.md).

    RU: ln(nlikes+1) * theta_src * exp(0.5 * user_taste_z); EN: theta_src * exp(user_taste_z).
    """
    if r.get("theta_src") is None:
        return None
    theta, taste = float(r["theta_src"]), float(r.get("user_taste_z") or 0.0)
    if channel == "tgchannelru":
        return math.log(r["nlikes"] + 1.0) * theta * math.exp(0.5 * taste)
    return theta * math.exp(taste)


FACTORS: dict[str, Callable[[Row, str], float | None]] = {
    # v2 production factors (meme_stats columns are NOT NULL)
    "lr_factor": lambda r, c: (r["nlikes"] + 1.0) / (r["nlikes"] + r["ndislikes"] + 1),
    "impr_factor": lambda r, c: (
        1.0 if r["raw_impr_rank"] <= 1 else CHANNEL_PARAMS[c]["impr_penalty"]
    ),
    "age_factor": lambda r, c: 1.0 if r["age_days"] < CHANNEL_PARAMS[c]["age_threshold"] else 0.8,
    "caption_factor": lambda r, c: 0.8 if r["has_caption"] else 1.0,
    "sent_factor": lambda r, c: (
        1.0 if r["nmemes_sent"] <= 1 else (r["nlikes"] + r["ndislikes"]) / r["nmemes_sent"]
    ),
    "src_quality_mult": _src_quality_mult,
    # quirk-fix arm (experiments/2026-11-01-crosspost-quirk-fix-ab.md): intended
    # impression penalty, and a neutral 1.0 for sources without enough history
    "impr_factor_q": lambda r, c: (
        1.0 if r["raw_impr_rank"] <= 1 else CHANNEL_PARAMS[c]["impr_penalty_intended"]
    ),
    "src_quality_q": lambda r, c: (
        1.0
        if r.get("src_signal") is None or not r.get("median_signal")
        else _src_quality_mult(r, c)
    ),
    "invited_boost": lambda r, c: 1.0 + min(r["invited_count"], 10) * 0.1,
    # v4: meme-level like volume (offline 2026-08-09)
    "like_volume_factor": lambda r, c: math.log(r["nlikes"] + 1.0),
    # v5 shadow: source Beta prior × user taste
    "v5_base": _v5_base,
    # v5c: RU blind-label study — relatable / tweet screenshots ≈ −0.1 zf each
    "content_mult_v1": lambda r, c: (
        0.85
        ** (int(r.get("relatable") is True) + int(r.get("content_format") == "tweet_screenshot"))
    ),
    # v5f: within-source forward-rate percentile of the source post; missing → 1.0
    "src_fwd_mult": lambda r, c: (
        1.0 if r.get("src_fwd_pct") is None else 0.5 + float(r["src_fwd_pct"])
    ),
}

_V2 = (
    "lr_factor",
    "impr_factor",
    "age_factor",
    "caption_factor",
    "sent_factor",
    "src_quality_mult",
    "invited_boost",
)
_V2Q = tuple(
    {"impr_factor": "impr_factor_q", "src_quality_mult": "src_quality_q"}.get(f, f) for f in _V2
)
SCORES: dict[str, tuple[str, ...]] = {
    "v2": _V2,
    "v4": (*_V2, "like_volume_factor"),
    "v5": ("v5_base",),
    "v5c": ("v5_base", "content_mult_v1"),
    "v5f": ("v5_base", "src_fwd_mult"),
    "v2q": _V2Q,
    "v4q": (*_V2Q, "like_volume_factor"),
}
# crossposting.score_version / decision_log.score_version for the picking score.
SCORE_VERSION = {"v2": 2, "v4": 4, "v5": 5, "v5c": 6, "v5f": 7, "v2q": 8, "v4q": 9}

PRESELECT = {"tgchannelru": "v4", "tgchannelen": "v2"}
LIVE = {"tgchannelru": "v4", "tgchannelen": "v2"}
# Live A/B: each decision picks one arm at random and uses it for both PRESELECT and
# LIVE. Remove the channel's entry to end the test (PRESELECT/LIVE apply again).
AB_ARMS = {"tgchannelru": ("v4", "v4q"), "tgchannelen": ("v2", "v2q")}


def score(row: Row, channel: str, name: str) -> float | None:
    vals = [FACTORS[f](row, channel) for f in SCORES[name]]
    return None if None in vals else math.prod(vals)


def score_all(row: Row, channel: str) -> tuple[dict[str, float | None], dict[str, float | None]]:
    factors = {name: f(row, channel) for name, f in FACTORS.items()}
    scores = {
        name: None if any(factors[f] is None for f in fs) else math.prod(factors[f] for f in fs)
        for name, fs in SCORES.items()
    }
    return factors, scores
