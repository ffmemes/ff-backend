# Experiment: Bot→channel ML lab (offline)

Created: 2026-08-11  
Status: **active — offline only**  
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
