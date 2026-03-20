# Experiment: Cold Start 3-Phase Adaptive System

**Status:** active
**Created:** 2026-03-20
**Measure after:** 2026-03-27 (7 days)

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

## Metrics After

*(Fill in after 2026-03-27)*

## Conclusion

*(Fill in after measurement)*
