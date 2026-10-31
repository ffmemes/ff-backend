---
id: cold_start_fresh_viral_v1
status: killed
hypothesis: Same cold-start floors but only memes from the last 30 days, newest first, lift first tap / first like
primary_metric: first tap
guardrails: reached-5, block within 1h, empty queue for new users
unit: user
variants: control:50,treatment:50
started: 2026-09-07
check_on: 2026-09-14
decided: 2026-10-30
result: first tap 60.0% control vs 48.5% treatment, blocked <1h 19 vs 27 (n 95/99)
learning: For a first impression, all-time proven hits beat fresh memes
code: COLD_START_FRESH_VIRAL_EXPERIMENT_ENABLED=false, src/recommendations/cold_start_experiments.py
readout: docs/analyst/onboarding-funnel.sql
---

# H10 — Fresh channel-quality memes as CS1 (A/B)

| Field | Value |
|-------|--------|
| **ID** | `cold_start_fresh_viral_v1` |
| **Status** | **KILLED 2026-10-30**: first tap 60.0% C vs 48.5% T, blocked<1h 19 vs 27 (n 95/99). Flag default off |
| **Kill switch** | `COLD_START_FRESH_VIRAL_EXPERIMENT_ENABLED` |
| **Code** | `src/recommendations/cold_start_experiments.py`, `cold_start_explore(max_age_days=)` |
| **Labels** | `cold_start_explore_fresh` / `_guarded` vs classic `cold_start_explore` |

## Hypothesis

Same CS floors, but only memes **created in the last 30 days**, newest first,
lifts first-tap / first-like vs all-time `lr_smoothed` hits. Empty fresh pool
fills from classic CS so we never starve the first session.

50/50 `sha256(experiment_id:user_id)%2` on true-new CS1 (`nmemes_sent < 6`,
`nsessions <= 1`). Observational 90d did **not** show an age→like gap (~22%
both); this A/B is the actual test.

## Decision rules (day-7, ≥80 new users/arm if we get them)

**Keep treatment / ship default** if first-tap ≥ control +5 pp (or first-like
+3 pp), reached-5 not down, invites/1k not down.  
**Disable flag** if first-tap down, block-in-1h up, or empty-queue for new users.

## Next check

**2026-09-14** — assignment counts + first-tap by variant.
