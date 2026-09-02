# `recently_liked` Blender V2 Guardrail Checkpoint

Date: 2026-06-17
Historical issue: FFM-1570
Decision: continue passive measurement; no winner, expansion, or rollback

## What The Checkpoint Showed

- The aggregate like-rate guardrail breach was heavily affected by an
  imbalanced high-volume-skipper cohort.
- After excluding that predeclared cohort, treatment like rate was better than
  control, so the aggregate breach was not sufficient evidence that the
  treatment itself harmed like rate.
- Session depth remained weaker in treatment. The experiment therefore did not
  establish a product win.
- The original minimum-sample gate was accumulating too slowly to support a
  timely decision.

## Decision

Keep the experiment passive/background-only and do not declare a winner. Do not
roll out or roll back from this checkpoint alone. Any later read must separate
target exposure from unrelated recommendation-engine mix and report cohort
composition alongside aggregate metrics.

## Reusable Lesson

Randomization is not enough when a small, high-volume behavioral cohort can
dominate event-weighted metrics. Define cohort balance and user-level metrics
before enrollment, and reject sample gates that cannot produce a decision in a
reasonable period.
