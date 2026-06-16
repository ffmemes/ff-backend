# Experiment: Goat Per-User Recency Filter

**Status:** active
**Created:** 2026-04-12
**Deployed:** 2026-04-13 (PR #162, commit 97f188a)
**Measure after:** 2026-04-27 (14-day window from deploy)

## Hypothesis

The goat engine has the **best continuation rate (98%)** of all engines but suffered LR decline from 44% to ~16% over 6 days due to pool exhaustion — the same top-ranked GOATs are served repeatedly to users who already saw them. Adding a per-user recency filter (exclude memes sent to the user in the last 30 days) will rotate the GOAT pool per-user, restoring fresh high-quality content delivery.

## Changes Made

- `src/recommendations/candidates.py` (goat function): Added per-user recency filter in SCORES CTE. PR #162, commit 97f188a shipped the original filter; 2026-06-16 correction changed the filter signal from `reacted_at` to `sent_at`, so recently sent but unreacted memes are excluded too.

## Metrics to Track

| Metric | Baseline (pre-experiment) | Target |
|--------|--------------------------|--------|
| Goat engine LR | 39.4% (7d pre-deploy) | >=35% (maintain, no regression) |
| Session length (median) | 30 (7d rolling) | >=18 (no regression) |
| WAU | 676 (organic baseline) | >=650 (no regression) |
| Session continuation rate (goat) | 97.8% | >=95% (no regression) |

## Success Criteria

- Goat LR >=35% (maintain current healthy level, prevent future pool exhaustion)
- No regression in session length (>=18 median)
- No regression in WAU (>=650 organic baseline)
- Goat continuation rate >=95%

## Metrics Before

*Filled by analyst 2026-04-13 (pre-deploy baseline):*

| Metric | Baseline value |
|--------|---------------|
| Goat LR (7d rolling) | 39.4% |
| Goat continuation rate (7d) | 97.8% |
| Goat volume (daily avg) | ~62/day (Apr 10-12) |
| Session length (7d median) | 30 |
| WAU | 676 |
| North Star | 30 |

**Note:** Original experiment doc cited ~16% goat LR (pool exhaustion era). That was resolved by prior production fixes (d830ad1: threshold relaxation, 1d4c830: quality thresholds). Current 39.4% LR is the real pre-experiment baseline. Experiment success criterion should focus on **maintaining LR ≥35% and preventing future pool exhaustion** rather than LR recovery.

## Metrics After

*To be filled by analyst after 14-day measurement window*

## Conclusion

*To be filled after measurement window*
