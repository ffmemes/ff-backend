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


def attach_v5_ranks(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add shadow_v5_rank (1=best) + shadow_v5_pick_meme_id without reordering."""
    if not candidates or any(c.get("score_v5") is None for c in candidates):
        return candidates
    order = sorted(range(len(candidates)), key=lambda i: -candidates[i]["score_v5"])
    for rank, i in enumerate(order, start=1):
        candidates[i]["shadow_v5_rank"] = rank
    pick = candidates[order[0]]["meme_id"]
    for c in candidates:
        c["shadow_v5_pick_meme_id"] = pick
    return candidates
