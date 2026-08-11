# Bot → channel crosspost ML lab

**Offline only.** Predict RU channel 24h quality (forwards / f1k / HIT) from
pre-post in-bot signals + source prior + premium composition.

## Principle

| SQL (`sql/`) | Local (Polars + sklearn) |
|--------------|--------------------------|
| Quantiles, coverage, quintile lifts | Feature matrix, models |
| Leakage-safe aggregates when cheap | Time-split train/eval |

## Setup

```bash
# from repo root, with ANALYST_DATABASE_URL in env
set -a; source .env; set +a   # or export ANALYST_DATABASE_URL=...

pip install polars pyarrow scikit-learn asyncpg numpy   # if needed
```

## Pipeline

```bash
cd experiments/ml-crosspost-bot2channel

# 1) SQL EDA (optional if reports/eda-sql.md already filled)
psql "$ANALYST_DATABASE_URL" -f sql/01_labels_and_quantiles.sql
psql "$ANALYST_DATABASE_URL" -f sql/02_coverage.sql
psql "$ANALYST_DATABASE_URL" -f sql/03_quintile_lifts.sql
psql "$ANALYST_DATABASE_URL" -f sql/04_source_prior_sanity.sql

# 2) Export raw layers
python export_raw.py --days 180

# 3) Build meme-level dataset
python build_dataset.py

# 4) Local EDA extras
python eda_local.py

# 5) Simple models vs v4 baseline
python train_eval.py
```

Outputs:

- `data/raw/*.parquet` (gitignored)
- `data/dataset.parquet`
- `reports/eda-sql.md`, `reports/eda-local.md`, `reports/*-models.md`

## Anti-overfit

- Time split only; HIT p75 from **train**
- ≤12 features; shallow trees
- Always compare to `v4_proxy = ln(pre_likes+1)` and `src_prior_f1k`
- No production ranker changes from this folder
