# Cold-Start Candidate Filter Post-Gate Readout

Date: 2026-07-29
Paperclip source: FFM-1939
Decision: complete as a directional success; retain the guarded behavior

## Result

The checkpoint included 37 guarded users, clearing the predeclared directional
sample gate.

| Cohort | Reached ten sends |
|---|---:|
| Guarded treatment | 32.4% |
| Pre-experiment baseline | 26.8% |
| Concurrent control | 11.1% |

The treatment improved against both comparisons, although it did not reach the
stretch target of 35%. First-meme continuation and first-10 like-rate
guardrails passed. No treatment leakage into unrelated routing was observed.

## Decision

Complete the experiment as a directional success and keep the guarded behavior.
Do not broaden the source exclusions or change mature-user routing from this
sample. Future work should be justified by a new position-level hypothesis,
not by reopening this completed measurement loop.

## Reusable Lesson

A modest sample can support a bounded decision when the directional sample gate,
baseline, control, and regression guardrails are declared before the readout.
