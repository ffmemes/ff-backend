# Paperclip Experiment Retrospective — 2026

Status: concluded as a product-development experiment

Paperclip helped coordinate autonomous work, but it did not become a reliable
source of truth. Durable product decisions now belong in Git next to the code,
queries, and experiment definitions they explain.

This retrospective preserves the reusable lessons. It is not a Paperclip
backup and does not make the Paperclip service safe to delete. A full private
archive is still required for database history, worktrees, unmerged branches,
integration state, and restore testing.

## What Produced Value

- Narrow investigations with a concrete decision at the end.
- Experiment files with an owner, rollout gate, rollback switch, and a dated
  measurement checkpoint.
- Small reusable SQL files committed beside their readouts.
- Explicit `continue`, `complete`, `rollback`, or `no change` conclusions.
- Separating technical health from product impact. A path can work correctly
  and still be too weak to expand.

## What Did Not Scale

- Issue and heartbeat volume grew much faster than shipped decisions.
- Multiple issues often described the same experiment at different stages.
- Reports remained in Paperclip instead of landing in Git, so later agents
  could not reliably discover them.
- Drafts and partial measurements were too easily mistaken for outcomes.
- Long-running sample gates created recurring status work without producing a
  timely product decision.
- Paperclip worktrees and branches became a second, weakly governed code store.

## Durable Operating Rules

1. Git is the source of truth for code, experiment state, incident reports,
   runbooks, and durable product learnings.
2. An experiment is not complete until its readout and conclusion are committed.
3. Partial reports may inform a decision, but must not create follow-up work by
   default. Create work only when the evidence changes a decision.
4. Keep at most two active product experiments unless the owner explicitly
   approves more.
5. A measurement gate must have an expected time-to-sample and a fallback
   decision date. An impractically slow gate is an experiment-design flaw.
6. Automation should report business outcomes, not only successful heartbeats.
7. Temporary orchestration systems must never be the only copy of useful work.

## Preserved Decisions

| Paperclip source | Durable Git artifact | Disposition |
|---|---|---|
| FFM-187 | [`docs/incidents/2026-04-01-db-pool-exhaustion.md`](../incidents/2026-04-01-db-pool-exhaustion.md) | Root cause and prevention retained; environment-specific details removed. |
| FFM-1437, FFM-1933 | This retrospective | Experiment-cap and outcome-discipline lessons consolidated. |
| FFM-1570 | [`docs/analyst/readouts/2026-06-17-recently-liked-blender-v2-checkpoint.md`](../analyst/readouts/2026-06-17-recently-liked-blender-v2-checkpoint.md) | Guardrail checkpoint retained. |
| FFM-1590 | [`docs/analyst/readouts/2026-06-25-inline-share-canary-readout.md`](../analyst/readouts/2026-06-25-inline-share-canary-readout.md) | Decision retained; reusable SQL was already in Git. |
| FFM-1744, FFM-1871 | [`docs/analyst/readouts/2026-07-13-cold-start-first10-quality-readout.md`](../analyst/readouts/2026-07-13-cold-start-first10-quality-readout.md) | Mutable measurement log condensed into the decision-grade checkpoint. |
| FFM-1861 | [`docs/analyst/readouts/2026-07-09-north-star-depth-dive.md`](../analyst/readouts/2026-07-09-north-star-depth-dive.md) | Diagnostic conclusion retained. |
| FFM-1883 | [`docs/analyst/readouts/2026-07-18-cold-start-candidate-filter-spotcheck.md`](../analyst/readouts/2026-07-18-cold-start-candidate-filter-spotcheck.md) | Early sample warning retained. |
| FFM-1939 | [`docs/analyst/readouts/2026-07-29-cold-start-candidate-filter-readout.md`](../analyst/readouts/2026-07-29-cold-start-candidate-filter-readout.md) | Final decision retained and experiment marked complete. |

## Intentionally Not Copied To Public Git

- Raw daily status reports that were superseded by a final readout.
- Duplicate SQL already tracked in `docs/analyst/`.
- Publication images and marketing drafts without a durable product decision.
- Operational metadata, internal URLs, integration identifiers, credentials,
  customer identifiers, and private workspace state.
- Unmerged branches or dirty worktrees. They require a private Git bundle and
  patch archive before Paperclip retirement, not publication in this repo.

## Retirement Boundary

The Paperclip experiment can be considered finished, and no new product work
should depend on it. Stopping or deleting the service is a separate operations
change. It requires a verified private export for every tenant, artifact hash
manifests, Git bundles for all worktrees, integration shutdown, credential
rotation, and a restore test before any volume or database is removed.
