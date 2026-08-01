# Experiment: Cold Start Candidate Filter

Created: 2026-07-14
Status: completed - directional success
Owner: ceo
Implementer: CTO
Implementation Issue: FFM-1882
Verification Issues: FFM-1883, FFM-1939
Deployed: 2026-07-16 in PR #331 (`f18ae381`)
Measured: 2026-07-29

## Hypothesis

True-new users were not primarily failing on the first meme. The July 13
first-10 readout showed first-meme continuation at 87.5%, but only 58.9% of
true-new users reached five sends and 26.8% reached ten. Excluding weak source
slices from cold-start positions 2–10 should improve depth without changing the
mature-user feed.

## Changes Made

- Scoped the treatment to true-new cold-start users.
- Added a feature-flagged candidate-source guardrail.
- Preserved the existing fallback path to prevent candidate starvation.
- Persisted guarded recommendation attribution for measurement.
- Kept mature-user routing and `recently_liked_blender_v2` out of scope.

Rollback: set `COLD_START_CANDIDATE_GUARDRAILS_ENABLED=false`.

## Metrics Before

2026-07-13, fourteen-day true-new cohort (56 users):

- First-meme continuation: 87.5%.
- First-10 like rate: 39.5%; continuation: 69.8%.
- Reached five sends: 58.9%.
- Reached ten sends: 26.8%.
- Second-session users: 55.4%.
- Position-two continuation: 62.0%.

## Success Criteria

- Reached-10 improves from 26.8% to at least 35%, or is directionally positive
  with at least 30 treatment users.
- First-meme continuation does not fall below 84%.
- First-10 like rate does not fall by more than three percentage points.
- No candidate starvation or routing leakage.

## Metrics After

2026-07-29 checkpoint:

- Guarded treatment users: 37.
- Reached ten sends: 32.4% treatment versus 26.8% pre-experiment baseline and
  11.1% concurrent control.
- First-meme continuation and first-10 like-rate guardrails passed.
- No unrelated-routing leakage was observed.

The early six-user spot check was intentionally non-decisive; see
[`2026-07-18-cold-start-candidate-filter-spotcheck.md`](../../docs/analyst/readouts/2026-07-18-cold-start-candidate-filter-spotcheck.md).
The final evidence is in
[`2026-07-29-cold-start-candidate-filter-readout.md`](../../docs/analyst/readouts/2026-07-29-cold-start-candidate-filter-readout.md).

## Conclusion

Directional success. The treatment cleared the declared 30-user alternative
gate and improved reached-10 versus both baseline and control without breaching
the first-meme, like-rate, fallback, or routing-scope guardrails.

Keep the guarded behavior. Do not broaden exclusions or change mature-user
routing without a new hypothesis and experiment.
