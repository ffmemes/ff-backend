# Experiment: Cold Start Candidate Filter

Created: 2026-07-14
Status: active - implementation in PR
Owner: ceo
Implementer: CTO
Implementation Issue: FFM-1882
Verification Issue: FFM-1883
Deployed: pending
Measure after: 2026-07-28

## Hypothesis

True-new users are not primarily failing on the first meme. The July 13 first-10
readout showed first-meme continuation at 87.5%, but only 58.9% of true-new
users reached five sends and 26.8% reached ten. If the cold-start candidate
pools exclude weak source slices for positions 2-10, reached-10 and first-10
continuation should improve without changing the mature-user feed.

## Changes Planned

- Scope the treatment to true-new cold-start users only.
- Add a feature-flagged treatment path for cold-start candidate selection.
- Start with source-level guardrails from the July 13 readout:
  `https://vk.com/dfzwe4`, `https://vk.com/eternalclassic`,
  `https://t.me/ukrmemesmineproblemes`, and `https://t.me/hindi_jokes_desi_memes`.
- Avoid a broad language reweight in v1. EN/RU mix should be measured as a
  guardrail, not forced from a 56-user sample.
- Preserve existing fallbacks so empty pools route to the current
  `text_light_lr_smoothed` / `best_uploaded_memes` behavior rather than
  starving users.
- Keep `recently_liked_blender_v2` untouched because it is a mature-user
  experiment with its own 2026-07-22 checkpoint.

## Implementation Notes

- Rollback: set `COLD_START_CANDIDATE_GUARDRAILS_ENABLED=false`.
- Treatment attribution: guarded candidates are persisted as
  `cold_start_explore_guarded` or `cold_start_adapt_guarded` in
  `user_meme_reaction.recommended_by`.
- Fallback rate: use recommendation diagnostics `fallback_used`, grouped by
  `cold_start_candidate_guardrails_applied`.

## Metrics Before

2026-07-13 readout, 14-day true-new cohort:

- Cohort users: 56.
- First-meme LR: 41.4%; first-meme continuation: 87.5%.
- First-10 LR: 39.5%; first-10 continuation: 69.8%; first-10 quality score: -0.179.
- Reached 5 users: 33/56 (58.9%).
- Reached 10 users: 15/56 (26.8%).
- Second-session users: 31/56 (55.4%).
- Position 2 continuation: 62.0%.
- Positions 6-7 continuation: 51.9-52.2%.
- 2026-07-14 health: North Star 21.0 vs previous 21.0, no severity incident;
  `recently_liked_blender_v2` sample gate remains unmet at 357 control / 400 treatment.

## Success Criteria

- Treatment reached-10 improves from 26.8% to at least 35% after the
  2026-07-28 checkpoint, or reaches a directionally positive lift with at least
  30 treatment users.
- Positions 2-5 continuation improves by at least 5pp versus baseline/control.
- First-meme continuation does not fall below 84%.
- First-10 LR does not fall by more than 3pp.
- No product-health incident: North Star does not drop by more than 10% week
  over week, stats remain fresh, and candidate pool fallback rate does not spike.

## Failure Criteria

- Treatment reached-10 is flat or worse after the checkpoint with enough users.
- First-meme continuation drops below 84% or first-10 LR drops by more than 3pp.
- Cold-start pool exhaustion causes fallback-heavy recommendations or visible
  delivery issues.
- The implementation changes mature-user routing, `recently_liked_blender_v2`,
  moderator low-sent quota, or unrelated engines.

## Guardrails

- Feature flag or equivalent fast rollback path required before production exposure.
- Report source/language mix, fallback rate, first-10 positions, reached-5,
  reached-10, second-session users, first-meme continuation, first-10 LR, and
  first-10 continuation.
- Preferred Analyst checkpoint artifact:
  `experiments/reports/2026-07-28-cold-start-candidate-filter-readout.md`.
- No Comms post until the experiment produces a user-facing result, not just an
  internal filter launch.

## Metrics After

Pending 2026-07-28 readout.

## Conclusion

Pending.
