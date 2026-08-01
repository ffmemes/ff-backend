# North Star Session-Depth Dive

Date: 2026-07-09
Paperclip source: FFM-1861
Decision: no emergency engine rollback; investigate middle-position quality

## Finding

The seven-day median session depth softened from 23 to 22, then 21 and 20. The
change was real, but the evidence did not support an outage, stale measurement,
or a single deterministic recommendation-engine regression.

The weakness was concentrated in the middle of sessions and among mature
users. First-position behavior did not explain the full decline. That pointed
to candidate quality and handoff between recommendation sources rather than a
broken first impression.

## Decision

- Do not perform a broad rollback from this readout.
- Measure position-level continuation and recommendation-source mix.
- Keep cold-start and mature-user experiments analytically separate.
- Treat service health, data freshness, and product-depth regression as three
  independent checks.

## Reusable Lesson

A median decline can come from several small distribution shifts. Diagnose it
by user maturity, session position, and source mix before changing a global
ranking rule.
