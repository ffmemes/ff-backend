# Exact-Meme Inline Share Canary Readout

Date: 2026-06-25
Historical issue: FFM-1590
Decision: end the canary; do not expand

## Result

The inline path worked technically, but adoption was too weak to justify more
exposure:

- 164 users were assigned to the canary.
- One user produced two chosen inline results.
- Existing URL-based sharing produced stronger observed use during the same
  evaluation.

The canary therefore demonstrated feasibility, not product demand.

## Decision

End the canary without expansion. Keep URL sharing as the supported path and
revisit inline sharing only if a new distribution hypothesis supplies a clearer
user trigger and a realistic activation target.

## Measurement

The reusable query is tracked in
[`docs/analyst/inline-share-canary-readout.sql`](../inline-share-canary-readout.sql).
The query separates assignment, result choice, and URL-share behavior so a
working transport path is not mistaken for successful adoption.
