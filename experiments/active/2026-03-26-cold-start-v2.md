# Experiment: Cold Start v2 — Quality-First Phase 1

**Status:** active
**Created:** 2026-03-26
**Measure after:** 2026-04-09 (14-day window)

## Hypothesis

The cold_start_3phase experiment (FAILURE, 2026-03-26) used diversity-first Phase 1 (DISTINCT ON meme_source_id — one best meme from each top source). This produced 0% first-meme LR across 28 new users and only 24.2% 10-meme retention.

Root cause: diversity guarantees variety, not quality. New users with no taste signal need the bot's objectively best memes first — not the most heterogeneous selection.

**Quality-first hypothesis:** Serving memes with proven social proof (≥20 explicit reactions, ≥40% lr_smoothed), ordered by like rate, will maximise first-impression quality. Phase 2 (cold_start_adapt) then calibrates on real reactions as before.

## Changes Made

- `src/recommendations/candidates.py`: Replaced `cold_start_explore()` filter and ordering:
  - Old: `MS.nmemes_sent >= 20 AND MS.lr_smoothed > 0.45`, ORDER BY `lr_smoothed DESC`
  - Initial new: `(MS.nlikes + MS.ndislikes) >= 50 AND MS.lr_smoothed >= 0.40`, ORDER BY `lr_smoothed DESC, total_reactions DESC`
  - Fixed (2026-03-28): `(MS.nlikes + MS.ndislikes) >= 20 AND MS.lr_smoothed >= 0.40` — see fix below
  - Default limit: 15 → 5 (Phase 1 serves 5 memes)

### Fix (2026-03-28): Cold Start Explore Pool Was Empty

Phase 1 was not triggering for new users on Mar 27–28 (68+ users received `lr_smoothed` fallback instead). Root cause: reaction count threshold `>= 50` was too strict. `nlikes + ndislikes` counts only explicit likes/dislikes, not skips. At typical 30–40% explicit-reaction rates, reaching 50 reactions requires ~150 sends — far too strict for most memes including high-quality ones. Lowered to `>= 20` reactions, consistent with the GOAT pool's "enough statistical signal" benchmark (`GOAT_MIN_REACTIONS = 10`). Quality gate `lr_smoothed >= 0.40` retained unchanged.

## Metrics to Track

| Metric | Baseline (cold_start_3phase) | Target |
|--------|------------------------------|--------|
| 10-meme retention (new users) | 24.2% | >50% |
| First-meme LR (new users) | 0% | >20% |
| Median session length | 19 | ≥18 (no regression) |
| WAU | 502 | ≥500 (no regression) |

## Success Criteria

- New user 10-meme retention > 50%
- First-meme LR > 20%
- No session length regression (≥18)
- No WAU regression (≥500)

## Failure Criteria

- First-meme LR stays ≤10% after 14 days
- 10-meme retention stays below 30%
- Session length drops below 16

## Notes

- cold_start_adapt (Phase 2) remains unchanged — it performed well at 61.1% continuation
- Queue refill threshold (≤8) and on-demand reco limit (15) retained from prior experiment
- generate_cold_start_recommendations() (language change path) remains on lr_smoothed — low impact, rare event

### Fix (2026-03-29): Switch from lr_smoothed to raw like rate (FFM-83)

Phase 1 pool remained empty even after threshold fix (50→20) because `lr_smoothed` applies user-bias correction that normalizes popular memes toward 0. Max `lr_smoothed` among ≥20-reaction memes: 0.2786 — well below the 0.40 threshold.

**Decision:** Replace `lr_smoothed` with raw like rate (`nlikes / (nlikes + ndislikes)`) for the explore pool. Raw LR is the correct signal for cold start — new users have no history, so user-bias correction is meaningless. Raw LR ≥ 0.40 with ≥ 20 reactions gives a stable, self-sustaining pool of objectively high-quality memes.

- `candidates.py:386`: `lr_smoothed >= 0.40` → `(nlikes::float / NULLIF(nlikes + ndislikes, 0)) >= 0.40`
- `candidates.py:389`: ORDER BY raw LR DESC instead of lr_smoothed DESC
- Assigned to CTO via FFM-83

## Metrics After

*(Fill in after 2026-04-09)*

## Conclusion

*(Fill in after measurement)*
