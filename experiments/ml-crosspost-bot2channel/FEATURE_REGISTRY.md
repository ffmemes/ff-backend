# Feature registry — bot→channel (H8)

**Rule:** every feature used in training must be listed here.  
**Leakage:** only events with timestamp **&lt; posted_at** (channel post time).  
**Budget:** ≤12 features in primary model.

Last updated: 2026-08-11

## Labels (targets)

| Name | Definition | Source |
|------|------------|--------|
| `f1k_24h` | `1000 * forwards / views` at snap closest to +24h in [18h, 36h] | snapshots |
| `forwards_24h` | forwards at that snap | snapshots |
| `views_24h` | views at that snap | snapshots |
| `reactions_24h` | channel reactions at that snap | snapshots |
| `hit` | `f1k >= train_p75 OR forwards >= 12` (p75 fit on **train fold only**) | derived |

## Baselines (always report)

| Name | Definition | Notes |
|------|------------|--------|
| `v4_proxy` | `ln(pre_likes + 1)` | prod score_version=4 volume term |
| `src_prior_f1k` | mean f1k of **prior** same-source channel posts in 90d | leakage-safe |

## Primary features (v1 model)

| Name | Definition | Coverage | Leakage | Status |
|------|------------|----------|---------|--------|
| `pre_ln_likes` | `ln(count likes before post + 1)` | ~100% ≥5 likes | pre-post | **in** |
| `pre_lr` | likes / (likes+dislikes) pre-post | ~100% | pre-post | **in** (weak alone) |
| `pre_reacts` | all pre reactions count | ~100% | pre-post | **in** (strong linear) |
| `pre_engaged_likes` | likes with `sec_to_react` in [5, 60] | if sent_at present | pre-post | **in** |
| `pre_premium_like_frac` | premium likers / pre_likes | ~100% any premium | pre-post | **in** (weak alone) |
| `pre_premium_likes` | count premium pre-likes | high | pre-post | **in** |
| `src_prior_f1k` | see baseline | ~95% | prior posts only | **in** |
| `src_prior_n_log` | `ln(n prior source posts + 1)` | ~95% | prior posts only | **in** |
| `has_caption_i` | 1 if meme.caption | high | meme meta | **in** |
| `log1p_hours_in_bot` | `ln(hours from first pre-react to post + 1)` | high | pre-post | **in** |

## Candidate / later (not primary until registry + walk-forward)

| Name | Definition | Why wait |
|------|------------|----------|
| `n_taste_likes` | H7 cohort likes pre-post | needs #348 deploy + re-export |
| `maturity_band` | mid vs top pre_reacts | engineered after walk-forward |
| `src_bot_nlikes` | meme_source_stats point-in-time | weak leakage (table not historical) |
| `pre_instant_skip_rate` | fast dislikes / reacts | weak in EDA |

## Explicitly rejected as primary

| Name | Why |
|------|-----|
| bot like rate alone | flat vs channel f1k (many EDAs) |
| in-bot share users alone | ~2–3% coverage historically |
| raw payment / balance | no payment tables; balance unused |
| deep embeddings | n≈600, overkill / overfit |

## Generation pipeline

```text
export_raw.py   → data/raw/*.parquet
build_dataset.py → data/dataset.parquet  (applies registry transforms)
train_eval.py / validate.py  ← FEATURES from features.py (must match this doc)
```
