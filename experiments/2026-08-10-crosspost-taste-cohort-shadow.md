---
id: crosspost_taste_cohort_v1
status: killed
hypothesis: Likes from a fixed top-50 taste cohort add a weak signal for channel forwards on top of like volume
primary_metric: mean f1k: top vs bottom half by n_taste_likes (posted, n_taste >=1)
guardrails: shadow only, no pick change
unit: channel_post
variants: shadow (logged only)
started: 2026-08-10
check_on: 2026-08-24
decided: 2026-10-30
result: f1k top vs bottom half 28.52 vs 28.72 (n=287); taste>=1 vs taste=0 28.62 vs 29.87
learning: A hand-picked taste cohort that looked good offline (lift 1.19) carried no live signal
code: removed: src/crossposting/taste_cohort.py, data/ru_taste_cohort_v1.json (git history)
readout: docs/analyst/readouts/2026-10-30-experiment-closure.md
---

# H7 — Taste cohort soft signal (SHADOW)

| Field | Value |
|-------|--------|
| **ID** | `crosspost_taste_cohort_v1` |
| **Status** | **KILLED as signal 2026-10-30**: top vs bottom n_taste f1k 28.52 vs 28.72 (n=287). No canary |
| **Cohort** | `src/crossposting/data/ru_taste_cohort_v1.json` (top 50) |
| **Code** | `taste_cohort.py`, `_enrich_candidates_with_taste_shadow` |
| **SQL** | removed 2026-10-31 (killed; in git history) |
| **Experiment note** | `2026-08-10-crosspost-v4-and-taste-cohort.md` |

## Hypothesis

A fixed set of ~50 users whose historical likes co-occur with high channel
fwd/1k provide a **weak but real** additional signal (soft boost), not a
replacement for like volume.

## Offline (2026-08-10)

- top50 likes top-20% lift **1.19** vs all-likes **1.10**; beats random-50 p95 **1.14**
- coverage ≥1 taste like ~**18%** of posts → never sole filter

## Shadow fields on decision candidates

`n_taste_likes`, `taste_boost_shadow` (= `1+0.15*min(n,5)`), `taste_cohort_version`

## Predictions

| Date | Pass if |
|------|---------|
| **2026-08-24** | Among mature picks with n_taste≥1, higher n_taste half has higher mean f1k (n≥20) |
| Canary | Only if H6 not RED and shadow pass → optional soft boost flag |

## Not doing

- Hardcode 50 users as only ranker  
- Post less often until H6 mature fails  

## Refresh

`python scripts/crosspost_taste_cohort.py`

Design and frozen predictions: [2026-08-10-crosspost-v4-and-taste-cohort.md](2026-08-10-crosspost-v4-and-taste-cohort.md).
