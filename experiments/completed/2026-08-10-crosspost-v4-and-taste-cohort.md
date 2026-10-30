# Experiments: Crosspost RU v4 like-volume + taste-cohort shadow (H6 / H7)

Created: 2026-08-10  
Owner: engineer / analyst  
Status: **completed (2026-10-30)**: H6 kept at 100%, H7 killed as a signal  
Channel: `tgchannelru` (@fastfoodmemes)  
**Predictions frozen:** 2026-08-10 (this file + `experiments/HYPOTHESES.md` H6/H7)

Authoritative calendar also in `experiments/HYPOTHESES.md` (H6, H7).  
Do **not** edit pass/fail thresholds after freeze without a dated amendment;
fill **Metrics after** only.

---

## Context (what we already know)

1. Bot **like rate** does not predict channel forwards (r≈0).
2. **Like volume** does (residual + hybrid offline); shipped as **score_version=4**:
   `v2_score * ln(nlikes+1)`.
3. Channel is the ground-truth virality lab (views/forwards snapshots).
4. Frequency: **keep 5/day** — optimize pick quality, not post count.
5. Early v4 (n=4, age-matched ~6h): not worse than v2 peers (WATCH).

---

## H6 — score_version=4 meme like-volume (ONLINE)

| Field | Value |
|-------|--------|
| Code | `CROSSPOST_RU_MEME_LIKE_VOLUME_ENABLED` (default ON) |
| Started | 2026-08-10 ~05:20 UTC first post |
| Kill | env `false` |

### Predictions (falsifiable)

| Deadline | Prediction | Pass if | Fail / kill if |
|----------|------------|---------|----------------|
| **2026-08-12** | ≥8 mature (18–36h) v4 posts | volume ok | zero posts / empty pool |
| **2026-08-17** (~7d) | hit_rate & avg_fwd **not worse** than v2 14d by **>15%** relative | WATCH→GREEN | avg_fwd or f1k **−25%** with n≥15 → RED kill |
| Stretch | hit_rate **+3pp** vs v2 14d | ship keep | flat OK if not RED |

**HIT** = `f1k ≥ ~31` (rolling p75) **OR** `forwards_24h ≥ 12`.

Readout: `docs/analyst/crossposting-v4-like-volume.sql`

### Early baseline logged 2026-08-10

- v2 14d mature: avg_fwd **8.9**, f1k **26.2**, hit **38%**
- v4 early 4–12h (n=4): avg_fwd **6.8**, f1k **30.0** (age-matched, not mature)

---

## H7 — taste cohort soft signal (SHADOW → later canary)

| Field | Value |
|-------|--------|
| Status | **shadow only** (does not change pick) |
| Cohort | `src/crossposting/data/ru_taste_cohort_v1.json` (top 50) |
| Method | train 70% time-split; users with ≥8 pre-post likes; rank by avg f1k lift |
| Offline | top50 count top-20% lift **1.19** vs all-likes **1.10**; beats random-50 p95 **1.14** |
| Coverage | ~18% posts have ≥1 taste like — **soft boost only**, never sole filter |

### Shadow fields (decision_log candidates[])

- `n_taste_likes` — distinct cohort users who liked meme (any time; approx pre-post for new memes)
- `taste_boost_shadow` — `1 + 0.15 * min(n, 5)`
- `taste_cohort_version` — file version string

### Predictions (falsifiable)

| Deadline | Prediction | Pass if |
|----------|------------|---------|
| **2026-08-24** (~14d shadow) | Among posted memes with `n_taste_likes ≥ 1`, those in top half of `n_taste_likes` have **higher** 24h f1k than bottom half | Δ f1k > 0 and n≥20 with taste≥1 |
| Same | Shadow would-re-rank (if apply boost) disagrees with v4 pick on ≤40% of decisions | log only |
| **Canary gate** | Only if H6 not RED **and** taste prediction passes | then enable soft boost flag |

### Explicitly NOT predicted

- Hardcoding 50 users as the **only** ranker will not work (coverage).
- Taste alone will not beat `ln(nlikes+1)` without volume.

### Refresh cohort

```bash
python scripts/crosspost_taste_cohort.py --days 120 --top 50 --min-n 8
# commit updated JSON if lifts stable
```

---

## Frequency policy (decision recorded)

| Option | Decision |
|--------|----------|
| Post more often | **No** |
| Post less, only “sure hits” | **Defer** until H6 mature readout; optional later floor on predicted score |
| Keep 5/day MSK 8,10,14,16,21 | **Yes** |

---

## How future-me / agents check who was right

1. Open this file + `experiments/HYPOTHESES.md` H6/H7.
2. Run:
   - `docs/analyst/crossposting-v4-like-volume.sql`
   - taste shadow SQL in `docs/analyst/crossposting-taste-shadow.sql`
3. Fill **Metrics after** tables below with dates.
4. Mark H6/H7 pass/fail; if H6 fail → kill switch; if H7 pass → canary PR.

### Metrics after (fill in)

| Date | v4 n mature | avg_fwd | avg_f1k | hit% | v2 baseline hit% | H6 |
|------|-------------|---------|---------|------|------------------|-----|
| 2026-08-10 early | 0 | — | — | — | 38% | WATCH |
| 2026-08-13 interim | **10** (≥36h) | **8.30** | **22.89** | **20%** | 34.5% (n=87, −6% fwd / −12% f1k) | **WATCH** (not RED; not a win) |
| 2026-08-17 | | | | | | |

Full interim writeup: `docs/analyst/crossposting-v4-interim-readout.md`

| Date | posts with n_taste≥1 | top half f1k | bottom half f1k | H7 |
|------|----------------------|--------------|-----------------|-----|
| 2026-08-24 | | | | |

---

## Code map

| Piece | Path |
|-------|------|
| v4 ranker | `src/crossposting/service.py` `like_volume_enabled` |
| Taste cohort | `src/crossposting/taste_cohort.py` + `data/ru_taste_cohort_v1.json` |
| Shadow enrich | `_enrich_candidates_with_taste_shadow` |
| Recompute | `scripts/crosspost_taste_cohort.py` |
| Stats density | post-hook + hourly young collector (PR #347) |

## Conclusion (2026-10-30)

- **H6 v4 like-volume: KEEP at 100%.** RU image posts, 24h snapshot: v2 (Jun 11–Aug 10,
  n=299) f1k 26.2, hit 32.1% → v4 pooled (Aug 10–Oct 29, n=373) f1k 28.9, hit 41.0%
  (+8.9 pp, z≈2.4). Forwards are up 11% and views are flat. Caveat: manual v0 posts
  also rose (f1k 17.2 → 20.6), so part of the lift is channel drift.
- **H7 taste-cohort shadow: KILL as a signal, with no canary.** Across 287 posts with n_taste≥1,
  the top vs bottom half by n_taste gave f1k 28.52 vs 28.72. taste≥1 vs taste=0 gave 28.62 vs 29.87. The
  pre-registered Δ>0 test fails. The decision_log fields stay until the crossposting PR
  that replaces shadow scoring removes them.

Readout: [`docs/analyst/readouts/2026-10-30-experiment-closure.md`](../../docs/analyst/readouts/2026-10-30-experiment-closure.md).
