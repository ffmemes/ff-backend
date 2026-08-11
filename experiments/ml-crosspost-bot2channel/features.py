"""Canonical feature lists for bot→channel lab (keep in sync with FEATURE_REGISTRY.md)."""

from __future__ import annotations

# Primary model features (≤12)
FEATURES: list[str] = [
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
]

BASELINES: list[str] = [
    "v4_proxy",
    "src_prior_f1k",
]

LABELS: list[str] = [
    "f1k_24h",
    "forwards_24h",
    "views_24h",
    "reactions_24h",
]

# Walk-forward pass bars (frozen 2026-08-11)
PASS_LIFT_DELTA_VS_V4 = 0.05  # top20 f1k lift must be >= v4 + this
PASS_MIN_FOLDS = 2  # of 3 expanding folds
PASS_MAX_SPEARMAN_GAP = 0.25  # train - test spearman (overfit guard)
MIN_TEST_N = 80
