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

- Engine LR drops below 40% (quality degradation from stale memes)
- Median session length drops below 16

## Metrics After

*(Fill in after 2026-03-27)*

## Conclusion

*(Fill in after measurement)*
