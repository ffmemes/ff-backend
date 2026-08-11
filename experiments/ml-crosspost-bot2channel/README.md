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

# 2) Export raw layers from DB
#    --days 0 = all history (recommended). Lifetime labels ≫ 24h-snap labels.
python export_raw.py --days 0

# 2b) Optional: full channel history via Telethon (deeplink sc_{meme_id}_…)
#     Needs TELEGRAM_API_ID / HASH / SESSION_STRING (same as stats_collector / zshrc)
python export_channel_telethon.py --limit 0

# 3) Build meme-level dataset
#    lifetime = live views/forwards (~thousands of rows)
#    24h      = strict 18–36h snapshots (~600 rows when collector was dense)
python build_dataset.py --label-mode lifetime

# 4) Local EDA extras
python eda_local.py

# 5) Simple models vs v4 baseline (single 70/30 — exploratory)
python train_eval.py

# 6) Walk-forward validation (authoritative offline verdict)
python validate.py
```

**Feature list:** `FEATURE_REGISTRY.md` + `features.py` (must stay in sync).

Outputs:

- `data/raw/*.parquet` (gitignored)
- `data/dataset.parquet`
- `reports/eda-sql.md`, `reports/eda-local.md`, `reports/*-models.md`
- `reports/*-walkforward.md` (pass/fail vs v4)

## Anti-overfit

- Time split only; HIT p75 from **train**
- ≤12 features; shallow trees
- Always compare to `v4_proxy = ln(pre_likes+1)` and `src_prior_f1k`
- No production ranker changes from this folder
