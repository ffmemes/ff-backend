# Experiment: Cold Start 3-Phase Adaptive System

**Status:** active — EXTENDED
**Created:** 2026-03-20
**Measure after:** 2026-04-02 (14 days, extended from 7)
**Extended:** 2026-03-26

## Hypothesis

The old cold start (<30 memes) used a single engine: `lr_smoothed` with `min_sends=10`. This gives globally-popular memes but no personalization from the user's first reactions.

A 3-phase approach adapts faster to user taste:
- Phase 1 (0-5 memes): Diverse explore — one best meme from each top source (DISTINCT ON meme_source_id). Guarantees variety — user sees different "types" of memes before committing.
- Phase 2 (6-15 memes): Adapt — read the user's raw reactions (bypasses 15-min stats delay) and weight sources accordingly. Liked source gets boosted, disliked penalized.
- Phase 3 (16-30 memes): Transition blend — 50% adapt, 30% lr_smoothed, 20% like_spread.

**Expected outcome:** Higher D1 retention for new users (they see diverse, personalized content in first 30 memes vs generic popular memes).

## Changes Made

- `src/recommendations/candidates.py`: Added `cold_start_explore` and `cold_start_adapt` engines
- `src/recommendations/meme_queue.py`: Replaced single-engine cold start with 3-phase routing in `get_candidates()`; bumped queue refill threshold ≤2 → ≤8, limit 5 → 15
- `src/tgbot/senders/next_message.py`: Bumped on-demand reco limit 7 → 15

## Metrics to Track

| Metric | Baseline (pre-change) | Target |
|--------|----------------------|--------|
| D1 retention (new users) | Unknown (not tracked) | Improvement vs control |
| Median session length | 18 memes | ≥18 (no regression) |
| Cold start drop-off rate (<30 memes) | Unknown | Decrease |
| WAU | 515 | ≥500 (no regression) |

## Known Inconsistency

`generate_cold_start_recommendations()` (called on language change, `language.py:137`) still uses old approach (lr_smoothed). Low impact — rare event. Fix in follow-up.

## Success Criteria

- Median session length stays ≥17 (no regression)
- No increase in Sentry errors from cold start engines
- At least 1 new user cohort (7+ users) completes 30+ memes

## Failure Criteria

- Median session length drops below 16
- `cold_start_explore` returns empty for >5% of new users (query too restrictive)
- New Sentry errors from cold start logic

## Extension Notes (2026-03-26)

| Metric | Day-7 Snapshot | Status |
|--------|---------------|--------|
| cold_start_explore continuation | 34.5% (avg over 6 days) | ⚠️ Low (0% on 3/6 days) |
| cold_start_adapt continuation | 61.1% (avg over 6 days) | ⚠️ Below 96% baseline |
| WAU | 496 (vs 500 floor) | ⚠️ Just under floor |
| Median session length | 19 | ✅ No regression |
| First-meme LR (new users) | 0% (28 users) | ⚠️ Concerning |

**CEO decision 2026-03-26: EXTEND 7 more days (measure after 2026-04-02).**

Rationale:
- Sample sizes too small for conclusions (5–41 memes/day per engine). Statistical noise dominates.
- WAU dip (496 vs 500 floor) is within noise range — not a clear regression signal.
- Failure criteria NOT hit: session length at 19 (floor is 16), no Sentry errors.
- cold_start_adapt at 61.1% is more promising than explore's 0% days — may need to re-balance phases.
- Need more new users (currently 28-user cohort) for D1 retention signal.

Watch for: if cold_start_explore continues showing 0% continuation days at end of extension, phase 1 (diversity-first) likely fails the hypothesis. May need to swap phase 1 strategy.

## Metrics After (2026-03-26 — early conclusion)

| Metric | Result | Status |
|--------|--------|--------|
| cold_start_explore continuation | 18.8% LR / 36.4% continuation | ❌ Hypothesis falsified |
| cold_start_adapt continuation | 61.1% | ⚠️ Below baseline |
| 10-meme retention (new users) | 24.2% (28-user cohort) | ❌ Far below target |
| First-meme LR | 0% | ❌ Hypothesis falsified |
| WAU | 502 | ✅ No regression |
| Median session length | 19 | ✅ No regression |

## Conclusion

**FAILURE — concluded early (2026-03-26), before extension deadline.**

Root cause: diversity-first Phase 1 (DISTINCT ON meme_source_id) maximises heterogeneity, not quality. New users with zero taste signal need the best memes globally, not the most varied.

Action taken: Phase 1 replaced with quality-first selection (≥50 reactions, ≥40% LR) in Cold Start v2 experiment (2026-03-26-cold-start-v2.md). cold_start_adapt retained for Phase 2-3.
