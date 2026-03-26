# Experiment: Cold Start v2 — Quality-First Phase 1

**Status:** active
**Created:** 2026-03-26
**Measure after:** 2026-04-09 (14-day window)

## Hypothesis

The cold_start_3phase experiment (FAILURE, 2026-03-26) used diversity-first Phase 1 (DISTINCT ON meme_source_id — one best meme from each top source). This produced 0% first-meme LR across 28 new users and only 24.2% 10-meme retention.

Root cause: diversity guarantees variety, not quality. New users with no taste signal need the bot's objectively best memes first — not the most heterogeneous selection.

**Quality-first hypothesis:** Serving memes with proven social proof (≥50 reactions, ≥40% like rate), ordered by like rate, will maximise first-impression quality. Phase 2 (cold_start_adapt) then calibrates on real reactions as before.

## Changes Made

- `src/recommendations/candidates.py`: Replaced `cold_start_explore()` filter and ordering:
  - Old: `MS.nmemes_sent >= 20 AND MS.lr_smoothed > 0.45`, ORDER BY `lr_smoothed DESC`
  - New: `(MS.nlikes + MS.ndislikes) >= 50 AND MS.lr_smoothed >= 0.40`, ORDER BY `lr_smoothed DESC, total_reactions DESC`
  - Default limit: 15 → 5 (Phase 1 serves 5 memes)

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

## Metrics After

*(Fill in after 2026-04-09)*

## Conclusion

*(Fill in after measurement)*
