---
id: bot2channel_ml_lab_v1
status: killed
hypothesis: Simple models on pre-post bot features + source prior beat ln(pre_likes+1) for RU channel picks (then shadow v4_x_src_v1)
primary_metric: walk-forward top-20% f1k lift; live corr(shadow_score, f1k)
guardrails: no production pick change
unit: channel_post
variants: shadow (logged only)
started: 2026-08-11
check_on: 2026-08-25
decided: 2026-10-30
result: lifetime walk-forward HOLD (n=3889); live shadow corr -0.092 (n=363 posted), agreed vs disagreed f1k 29.01 vs 29.10
learning: A one-split offline win (lift 1.19) did not survive lifetime walk-forward or live shadow; require both before trusting a ranker
code: removed: experiments/ml-crosspost-bot2channel/ (commit 177cad0e), v4_x_src_v1 shadow fields
readout: docs/analyst/readouts/2026-10-30-experiment-closure.md
---

# Experiment: Bot→channel ML lab (offline)

Created: 2026-08-11  
Status: **completed (2026-10-30)**: H8 shadow killed as a signal  
Owner: analyst / engineer  
Code: `experiments/ml-crosspost-bot2channel/`

## Hypothesis

Simple models (linear / logistic / shallow trees) on **pre-post bot features +
source prior + premium composition** can rank RU channel candidates better than
`v4_proxy = ln(pre_likes+1)` alone, without overfitting.

## What we built

| Layer | Path |
|-------|------|
| SQL EDA | `sql/` + `run_sql_eda.py` → `reports/eda-sql.md` |
| Raw export | `export_raw.py` → `data/raw/*.parquet` (gitignored) |
| Dataset | `build_dataset.py` → `data/dataset.parquet` |
| Models | `train_eval.py` → `reports/2026-08-11-models.md` |

## Data snapshot (export 2026-08-11)

- **n labeled** = 624 (180d, image, mature 18–36h)
- pre-reactions rows = 93.6k; reactors = 2.4k
- avg pre_likes ≈ 55; premium among likers ≈ 42%
- f1k p50≈23.5, p75≈31; hit_rate (f1k≥30.9 ∨ fwd≥12) ≈ 27%

## SQL EDA takeaways

1. **pre_lr flat** on f1k (~23–25 across quintiles) — reconfirmed  
2. **pre_likes** non-monotonic; q5 best but q4 soft (saturation)  
3. **premium_frac** weak / non-monotonic alone  
4. **src_prior_f1k** corr ≈ 0.17 with outcome  

## Model results

### A) Single 70/30 (exploratory only)

| model | top20 lift f1k | AUC (HIT) | notes |
|-------|---------------:|----------:|-------|
| v4_proxy | 1.114 | 0.54 | baseline |
| src_prior only | 1.023 | 0.51 | weak alone |
| logreg_hit | 1.187 | 0.62 | looked good once |
| ridge_f1k | 1.142 | 0.60 | close |
| hgb depth3 | 1.086 / 1.018 | ~0.54 | **overfit** |

### B) Walk-forward (authoritative) — 2026-08-11

Report: `experiments/ml-crosspost-bot2channel/reports/2026-08-11-walkforward.md`  
Registry: `FEATURE_REGISTRY.md` · `validate.py`

| model | wins vs v4 (≥+0.05 lift) | mean lift f1k | mean gap ρ | PASS |
|-------|-------------------------:|--------------:|-----------:|:----:|
| **logreg_hit** | **2/3** | **1.190** | 0.00 | **YES** |
| **ridge_f1k** | **2/3** | **1.171** | 0.06 | **YES** |
| hgb | 1/3 | ~1.07–1.14 | **0.45–0.54** | no |
| v4_proxy | — | **1.080** | 0.03 | baseline |

**Offline verdict: PASS** (logreg + ridge).  
**Still do not change production pick** — next step is decision_log **shadow score only**.

Russian review writeup: `reports/2026-08-11-otchet-ru.md`

### Ridge direction (standardized, single split)

Positive: `pre_reacts`, `src_prior_f1k`, `src_prior_n_log`, `pre_premium_like_frac`  
Negative/weak: caption, raw `pre_ln_likes` once reacts in model (collinear)

## Decision rules

| Outcome | Action |
|---------|--------|
| Hold production v4 pick | **Yes** (H6 calendar still owns keep/kill) |
| Walk-forward | **Done PASS** logreg/ridge |
| Next | Shadow `ml_score` on decision_log (not sole ranker); add H7 taste after deploy |
| Kill lab models | If live shadow fails to correlate with 24h f1k |

## Explicitly not doing

- Deep nets  
- Random CV as truth  
- Taste-only ranker  
- Changing 5/day frequency from this lab  

## How to reproduce

```bash
set -a; source .env; set +a
cd experiments/ml-crosspost-bot2channel
python run_sql_eda.py
python export_raw.py --days 180
python build_dataset.py
python eda_local.py
python train_eval.py
```


## Deep lifetime re-run (same day)

- n=3889 (Telethon∪DB), walk-forward **HOLD** vs v4
- See `reports/2026-08-11-results.html` and `reports/2026-08-11-otchet-ru.md`
- Production: no change

## Conclusion (2026-10-30)

**KILL `v4_x_src_v1` as a ranking signal, with no canary.** Live shadow (n=388 decisions):
it disagreed with the prod pick 70.9% of the time. Among posted picks (n=363),
corr(shadow_score, f1k) = −0.092, and corr(prod final_score, f1k) = −0.047. Both
are range-restricted and near zero. Agreed vs disagreed picks: f1k 29.01 vs 29.10.
The "clearly better than v4" bar was not met. Offline lab code stays under
`experiments/ml-crosspost-bot2channel/` for reference. The decision_log shadow fields
stay until the crossposting PR that replaces shadow scoring removes them.


## Registry entry (moved from docs/growth/HYPOTHESES.md, 2026-10-31)

## H8 — Bot→channel ML lab (OFFLINE)

| Field | Value |
|-------|--------|
| **ID** | `bot2channel_ml_lab_v1` |
| **Status** | **KILLED as signal 2026-10-30**: offline HOLD vs v4, and the live shadow corr is −0.09 (see below) |
| **Code** | `experiments/ml-crosspost-bot2channel/` — removed 2026-10-30; recover from commit `177cad0e` |
| **Note** | `2026-08-11-bot2channel-ml-lab.md` |
| **Report** | `experiments/ml-crosspost-bot2channel/reports/2026-08-11-models.md` |

### Hypothesis

Simple linear/logistic models on pre-post bot features + source prior beat
`ln(pre_likes+1)` on time-holdout top-20% f1k lift without tree overfit.

### First result (2026-08-11)

- n=624 labeled; single 70/30: logreg lift 1.187 vs v4 1.114 (looked good once)
- HGB depth3 **overfits** — discard for ship

### Walk-forward (authoritative, 2026-08-11)

- 3 expanding folds (~93 test each); bar: lift ≥ v4+0.05 on ≥2/3 + spearman gap &lt;0.25
- **logreg PASS** (2/3, mean lift 1.190 vs v4 1.080)
- **ridge PASS** (2/3, mean lift 1.171)
- HGB FAIL (overfit gap ~0.5)
- Report: `experiments/ml-crosspost-bot2channel/reports/2026-08-11-walkforward.md`
- RU summary: `.../reports/2026-08-11-otchet-ru.md`
- **No production pick change** — next is shadow score only


### Deep lifetime re-run (2026-08-11 evening)

- Telethon full crawl: 11928 msgs, 4897 sc_ joinable → dataset **n=3889** (2023-11..2026-08)
- Label = lifetime f1k (TG now); HIT = f1k≥train p75
- Walk-forward: **HOLD** — logreg/ridge/HGB do **not** beat v4 on ≥2/3 folds
- Source prior often ≥ volume on long history; bot volume ~flat on lifetime
- HTML: `experiments/ml-crosspost-bot2channel/reports/2026-08-11-results.html`
- Hypothesis battery: hybrids volume×source lead mean lift; **no bar PASS**
  (`reports/2026-08-11-hypothesis-battery.html`)

### Shadow hybrid in decision_log (shipping)

| Field | Value |
|-------|--------|
| **Status** | **KILLED 2026-10-30**: corr(shadow, f1k) −0.092 on 363 posted picks, agreed vs disagreed f1k 29.01 vs 29.10. Fields stay until the crossposting PR replaces shadow scoring |
| **Formula** | `shadow_score = ln(nlikes+1) * src_quality_mult` |
| **Version** | `v4_x_src_v1` (+ `shadow_score_maturity` band) |
| **Code** | `src/crossposting/shadow_score.py`, `_build_decision_log` |
| **SQL** | removed 2026-10-31 (killed; in git history) |

Also logs `shadow_rank`, `shadow_pick_meme_id`, `shadow_vs_prod_disagree`.

### Next check

- After deploy: decision_log has `shadow_score` on candidates
- **2026-08-25**: shadow-hybrid SQL (now removed) — disagree rate + corr(shadow, f1k_24h)
- Canary soft boost only if live corr/lift clearly > v4 alone
- After H7 merge: re-export + optional taste feature
- Do not schedule as feed experiment
