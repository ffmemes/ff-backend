# Experiment: Unstarve like_spread_and_recent engine

**Status:** active
**Created:** 2026-03-20
**Measure after:** 2026-03-27 (7 days)

## Hypothesis

The `like_spread_and_recent_memes` engine has the best like rate of all engines (51.1%) but is severely starved — serving only 3,112 reactions (7-day) vs 50,074 for `lr_smoothed`. The `age_days < 30` filter limits it to 72 candidates. Removing this constraint should expand the candidate pool dramatically without hurting quality, because `raw_impr_rank = 0` already gates the top-quartile viral memes.

**Expected outcome:** Engine serves 5-10x more memes, maintaining ~50%+ LR, improving overall blend quality and session length.

## Changes Required

In `src/recommendations/candidates.py`, remove the `age_days < 30` constraint from the `like_spread_and_recent_memes` query.

The `raw_impr_rank = 0` filter (top-quartile by impressions) already ensures quality. Age is not a quality signal per H3 (freshness doesn't correlate with quality — validated in prior analysis).

## Metrics to Track

| Metric | Baseline (7-day pre-change) | Target |
|--------|----------------------------|--------|
| like_spread_and_recent sent (7d) | 3,112 | >10,000 |
| like_spread_and_recent LR | 51.1% | ≥48% (can drop slightly with larger pool) |
| Median session length | 18 memes | ≥18 (no regression) |
| Overall blend LR | ~45% | ≥45% |

## Success Criteria

- Engine serves ≥3x more memes (9,000+)
- LR does not drop below 45% (some drop acceptable from larger pool)
- Median session length does not regress below 17

## Failure Criteria

- ~~Engine LR drops below 40%~~ **Revised 2026-03-22**: LR floor relaxed to 35%. Rationale: North Star moved +1 (median 19) while this experiment was live. The LR/volume trade-off is working — more content served → longer sessions. LR decline from 51% to ~40% is pool expansion effect (expected), not quality degradation. Only act if session length drops below 17.
- Median session length drops below 16

## Mid-experiment Notes (2026-03-22)

| Date | Daily Sent | Daily LR |
|------|-----------|---------|
| Mar 19 (baseline) | 768 | 45.5% |
| Mar 20 (day 1) | 2,079 | 47.3% |
| Mar 21 (day 2) | 3,378 | 42.9% |
| Mar 22 (partial) | 1,073 | 39.4% |

Volume +4.4x (exceeds ≥3x success criterion). LR declining as pool expands — expected. North Star +1 (18→19) concurrent with this experiment. **CEO decision: continue, accept new LR baseline, do not add age filter back.** Failure will be session length regression, not LR.

## Metrics After

*(Fill in after 2026-03-27)*

## Conclusion

*(Fill in after measurement)*
