"""Crosspost shadow scorers — log only, never change production pick.

Primary hybrid from offline battery (H8 / hypothesis_battery):
  shadow_score = ln(nlikes + 1) * src_quality_mult

src_quality_mult is the same 0.5–2.0 clamp as the live ranker
(_compute_score_breakdown). Maturity band is a second logged variant.

Version string is frozen for decision_log analytics.
"""

from __future__ import annotations

import math
from typing import Any

SHADOW_VERSION = "v4_x_src_v1"
SHADOW_MATURITY_VERSION = "maturity_x_src_v1"

# Soft band from offline research (likes in bot before channel post)
_MATURITY_LO = 15
_MATURITY_HI = 120
_MATURITY_OVER = 200
_MATURITY_BOOST = 1.15
_MATURITY_DEMOTE = 0.85


def volume_factor(nlikes: int | float | None) -> float:
    return math.log(float(nlikes or 0) + 1.0)


def maturity_band_mult(nlikes: int | float | None) -> float:
    n = float(nlikes or 0)
    if _MATURITY_LO <= n <= _MATURITY_HI:
        return _MATURITY_BOOST
    if n > _MATURITY_OVER:
        return _MATURITY_DEMOTE
    return 1.0


def hybrid_shadow_fields(
    *,
    nlikes: int | float | None,
    src_quality_mult: float | None,
) -> dict[str, Any]:
    """Fields attached to each decision_log candidate (no re-rank)."""
    vol = volume_factor(nlikes)
    src = float(src_quality_mult) if src_quality_mult is not None else 1.0
    if not math.isfinite(src) or src <= 0:
        src = 1.0
    band = maturity_band_mult(nlikes)
    score = vol * src
    score_maturity = vol * src * band
    return {
        "shadow_version": SHADOW_VERSION,
        "shadow_vol": round(vol, 4),
        "shadow_src_mult": round(src, 4),
        "shadow_score": round(score, 6),
        "shadow_maturity_mult": round(band, 4),
        "shadow_score_maturity": round(score_maturity, 6),
        "shadow_maturity_version": SHADOW_MATURITY_VERSION,
    }


def attach_shadow_ranks(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add shadow_rank / shadow_rank_maturity (1=best) without reordering list."""
    if not candidates:
        return candidates

    def _ranks(key: str) -> dict[int, int]:
        order = sorted(
            range(len(candidates)),
            key=lambda i: float(candidates[i].get(key) or 0.0),
            reverse=True,
        )
        return {i: rank + 1 for rank, i in enumerate(order)}

    r_main = _ranks("shadow_score")
    r_mat = _ranks("shadow_score_maturity")
    for i, c in enumerate(candidates):
        c["shadow_rank"] = r_main[i]
        c["shadow_rank_maturity"] = r_mat[i]
        # Would this shadow have picked a different top-1 than production rank 1?
        c["shadow_disagrees_top1"] = bool(r_main[i] == 1 and c.get("rank") != 1)
    # Top-level convenience: does best shadow differ from production pick?
    if candidates:
        prod_top = candidates[0].get("meme_id")
        shadow_top_i = min(range(len(candidates)), key=lambda i: r_main[i])
        shadow_top = candidates[shadow_top_i].get("meme_id")
        for c in candidates:
            c["shadow_pick_meme_id"] = shadow_top
            c["shadow_vs_prod_disagree"] = shadow_top != prod_top
    return candidates
