---
id: onboarding_first_tap_v1
status: shipped
hypothesis: New-user growth is gated by first meme to first tap, not by the language picker or share skipping welcome
primary_metric: first tap % of got-meme, first like %, reached-5
guardrails: block within 1h
unit: user
variants: none (funnel scoreboard)
started: 2026-09-07
check_on: 2026-09-14
decided: 2026-09-07
result: 90d to 2026-09-07: 402 got a meme, 252 reacted, 150 silent; empty start 61% vs share 71%; 2026-10-30: never-got-meme rose 3.1% to 12.6%
learning: First tap is the onboarding leak; the 2026-10-30 rise came from the language picker (fixed by onboarding_default_language_v1)
code: 
readout: docs/analyst/onboarding-funnel.sql
---

# H9 — First-tap is the onboarding leak

| Field | Value |
|-------|--------|
| **ID** | `onboarding_first_tap_v1` |
| **Status** | **scoreboard** for H10/H11. **2026-10-30 flag:** users who never got a meme rose 3.1% → 12.6% (25/26 have no language row). Investigate the language picker |
| **Readout** | `docs/analyst/readouts/2026-09-07-onboarding-and-dormant-blast.md` |
| **SQL** | `docs/analyst/onboarding-funnel.sql` |

## Hypothesis

New-user growth is gated by **first meme → first tap**, not language picker
and not share skipping welcome. 90d (2026-09-07): 402 got a meme, 252 reacted,
**150** silent. Empty start 61% vs share 71%.

## Growth bar

First-tap % of got-meme; first-like %; reached-5. Secondary: non-self share
clicks and invites from the same cohort. Guardrail: block-in-1h.

## Next check

**2026-09-14** re-run `onboarding-funnel.sql`.

Rejected: 'fixing' share links that skip welcome/picker (90d share converts better than empty start).
