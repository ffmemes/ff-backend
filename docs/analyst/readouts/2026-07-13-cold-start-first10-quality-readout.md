# Cold-Start First-10 Quality Readout

Date: 2026-07-13
Historical issue: FFM-1871, consolidating the FFM-1744 measurement log
Decision: test candidate-source guardrails for positions 2–10

## Cohort

Fourteen-day true-new cohort: 56 users.

| Metric | Result |
|---|---:|
| First-meme like rate | 41.4% |
| First-meme continuation | 87.5% |
| First-10 like rate | 39.5% |
| First-10 continuation | 69.8% |
| First-10 quality score | -0.179 |
| Reached five sends | 33/56 (58.9%) |
| Reached ten sends | 15/56 (26.8%) |
| Started a second session | 31/56 (55.4%) |
| Position-two continuation | 62.0% |
| Position-six/seven continuation | about 52% |

## Interpretation

The first meme was not the primary bottleneck. Most users continued after it,
then the experience weakened across positions 2–10. Candidate-source slices
and handoff quality were a more plausible lever than another broad first-meme
ranking change.

The cohort was too small for a global language reweight. Language mix should be
reported as a guardrail, not forced from this sample.

## Decision

Run a feature-flagged candidate-source guardrail for true-new users only.
Preserve existing fallbacks, avoid changing mature-user routing, and evaluate
reached-5, reached-10, position continuation, like rate, source/language mix,
and fallback rate together.
