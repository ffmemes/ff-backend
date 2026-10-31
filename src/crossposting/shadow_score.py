"""Crosspost v5 shadow scorer — log only, never changes the production pick.

From the 2026-10-30 walk-forward study (target zf = log1p(forwards) minus
channel×week mean; see experiments/active/2026-10-30-crosspost-v5-shadow.md):

  RU: score_v5 = ln(nlikes+1) * theta_src * exp(0.5 * user_taste_z)
  EN: score_v5 = theta_src * exp(user_taste_z)        (like volume hurts on EN)

theta_src and user_taste_z come from ``_V5_SHADOW_QUERY`` in service.py.
Version string is frozen for decision_log analytics.
"""

from __future__ import annotations

import math
from typing import Any

SHADOW_V5_VERSION = "v5_src_beta_taste_v1"


def score_v5(
    channel: str,
    nlikes: int | float | None,
    theta_src: float,
    user_taste_z: float | None,
) -> float:
    theta = float(theta_src)
    taste = float(user_taste_z or 0.0)
    if channel == "tgchannelru":
        return math.log(float(nlikes or 0) + 1.0) * theta * math.exp(0.5 * taste)
    return theta * math.exp(taste)


def content_mult_v1(content_format: str | None, relatable: bool | None) -> float:
    """RU blind-label study 2026-10-30: relatable and tweet screenshots ≈ −0.1 zf each.

    Tags come from Describe Memes (meme.ocr_result); missing tags → 1.0.
    See experiments/active/2026-10-31-crosspost-content-tags.md.
    """
    return 0.85 ** (int(relatable is True) + int(content_format == "tweet_screenshot"))


def src_fwd_mult(src_fwd_pct: float | None) -> float:
    """score_v5f = score_v5 * (0.5 + src_fwd_pct); missing pct → 1.0.

    src_fwd_pct: within-source percentile of the source post's forwards/views
    (Telethon read at ~20–48h). Study 2026-10-31: Spearman with our crosspost
    forwards +0.52 RU / +0.28 EN. See
    experiments/active/2026-11-01-crosspost-src-forward-rate.md.
    """
    return 1.0 if src_fwd_pct is None else 0.5 + float(src_fwd_pct)


def attach_v5_ranks(candidates: list[dict[str, Any]], version: str = "v5") -> list[dict[str, Any]]:
    """Add shadow_{version}_rank (1=best) + shadow_{version}_pick_meme_id without reordering."""
    key = f"score_{version}"
    if not candidates or any(c.get(key) is None for c in candidates):
        return candidates
    order = sorted(range(len(candidates)), key=lambda i: -candidates[i][key])
    for rank, i in enumerate(order, start=1):
        candidates[i][f"shadow_{version}_rank"] = rank
    pick = candidates[order[0]]["meme_id"]
    for c in candidates:
        c[f"shadow_{version}_pick_meme_id"] = pick
    return candidates
