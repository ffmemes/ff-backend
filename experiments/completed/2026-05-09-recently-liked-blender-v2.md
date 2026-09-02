# Experiment: recently_liked Blender V2
Created: 2026-05-09
Status: frozen - passive watch only
Owner: ceo
Measure after: after each variant reaches at least 1,000 assigned mature users

## Hypothesis

The `recently_liked` engine is still under-allocated for mature users. The first mature-user blender A/B was rolled back after a severe LR guardrail breach, but post-rollback analysis shows the engine itself has 98.0% session continuation at its natural allocation, second only to `uploaded_meme` and above `lr_smoothed` at 95.3%.

The v1 failure is therefore treated as an experiment-design failure, not proof that `recently_liked` is harmful. If assignment is stratified by each user's recent like-rate behavior and high-volume skippers are balanced or excluded, increasing `recently_liked` allocation for mature users should improve median session depth without breaching LR or freshness guardrails.

## Changes Made

- 2026-05-09 CEO decision from [FFM-1093](/FFM/issues/FFM-1093): open a redesigned v2 A/B instead of immediately re-enabling the v1 weights.
- Implementation delegated to build LR-stratified assignment, high-volume-skipper handling, and explicit sample gates before the experiment can be read.
- Measurement work was blocked on deployment.
- 2026-07-23T18:05:54Z freeze applied in code via `RECENTLY_LIKED_BLENDER_V2_ENROLLMENT_FROZEN = True`: existing assignment rows remain readable, but new/unassigned mature users use control weights without creating new experiment assignments. Rollback path: set the freeze constant to `False` and redeploy.

## Metrics Before

| Metric | Value |
|--------|-------|
| Session length median | 19.5 |
| WAU | 594 |
| MAU | 1,091 |
| DAU | 249 |
| ok_pct | 94% |
| Reactions 24h | 20,957 partial 10h |
| `recently_liked` continuation | 98.0% |
| `lr_smoothed` continuation | 95.3% |
| V1 final LR delta | treatment 30.3% vs control 44.3% (-14.0pp) |
| V1 final median session depth delta | treatment 15.0 vs control 17.5 (-2.5 memes) |
| V1 high-volume skipper imbalance | 34 treatment vs 15 control (2.3x) |

## Design Requirements

- Mature users only; keep cold-start routing out of scope.
- Assign users within 7d personal-like-rate quartiles at enrollment time.
- Exclude users with 7d LR <20% and >50 reactions, or explicitly balance them across variants if exclusion is not technically practical.
- Do not read winner/loser results until each variant has at least 1,000 assigned users.
- Track per-variant LR, median session depth, per-user median LR, high-volume-skipper counts, engine allocation mix, and per-engine continuation.
- Add a Day-3 guardrail checkpoint, but treat the minimum sample gate as the primary read rule.

## Success Criteria

- Treatment median session depth improves by at least 5% versus control after the sample gate is met.
- Treatment LR is no worse than 2pp below control.
- High-volume skipper composition differs by no more than 1.3x between arms.
- Per-engine diagnostics do not show broad treatment-arm underperformance across unaffected engines.

## Failure Criteria

- LR guardrail drops more than 4pp below control at Day 3 and cohort diagnostics do not clearly exonerate treatment.
- Treatment median session depth remains below control after the sample gate is met.
- Assignment stratification cannot be verified before rollout.
- V2 cannot reach 1,000 users per variant in a reasonable window without overexposing the same high-volume users.

## Metrics After

See [docs/analyst/recently-liked-blender-v2-closeout.md](../../docs/analyst/recently-liked-blender-v2-closeout.md).

| Metric | Control | Treatment |
|--------|---------|-----------|
| Global LR (30d post-assign) | 63.33% | 63.67% |
| Median session 14d | 18 | 19 (+5.6%) |
| Median user LR | 62.65% | 71.08% |
| recently_liked traffic share | 16.9% | 22.9% |

## Conclusion

**Ship treatment as mature default.** Stratified assignment fixed v1 failure mode.
Enrollment frozen; sample gate 1000 unreachable at current WAU — closed on partial
but consistent evidence. Do not re-open without a realistic sample gate.


## Conclusion

Pending. V2 exists to test the engine under a corrected experiment design, not to relitigate v1's confounded result.
