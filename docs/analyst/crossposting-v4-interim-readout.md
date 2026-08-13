# Crosspost RU v4 interim readout (2026-08-13)

## Online (mature ≥36h, fair window)

| cohort | n | avg_fwd | avg_f1k | hit% (f1k≥30.9 ∨ fwd≥12) |
|--------|--:|--------:|--------:|-------------------------:|
| **v4** (since 2026-08-10) | **10** | **8.30** | **22.89** | **20%** |
| **v2** (21d before v4) | **87** | **8.83** | **25.96** | **34.5%** |
| Δ | | **−6%** | **−12%** | soft |

Total v4 posts live at readout: **17** (not all mature yet).

### Decision

| Option | Choice |
|--------|--------|
| RED kill (−25% avg) | **No** |
| Significant improvement | **No** |
| Status | **WATCH / hold v4 ON** until n_mature ≥15–20 (~2026-08-15…17) |
| Next hard gate | **2026-08-17** keep/kill per H6 |

**Interpretation:** fewer hits, avg shares slightly soft, reach OK. Not a win; not a collapse.

## Shadow hybrid (live log)

- Deployed with PR #349; fields on candidates after 2026-08-11 21:06 UTC
- ~8 decisions with `shadow_score` by 2026-08-13 morning; ~half disagree with prod top-1
- Too early for f1k compare of shadow-counterfactual (shadow pick usually not posted)

SQL: `docs/analyst/crossposting-shadow-hybrid.sql`

## Next experiments shipped after this readout

1. **n_sub_likes** shadow field (channel members ∩ bot likes) — decision_log only  
2. **sync_channel_membership.py** — densify membership for active bot users  
3. Offline next-wave + H9 already recorded under experiments/ml-crosspost-bot2channel/

## Do not

- Ship multi-feature ML as hard ranker  
- Increase post frequency  
- Treat WATCH as success  
