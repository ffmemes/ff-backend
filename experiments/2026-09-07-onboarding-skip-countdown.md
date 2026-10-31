---
id: onboarding_skip_countdown_v1
status: shipped
hypothesis: Removing the ~9 s 3-2-1 countdown and sending the first meme right after welcome raises first tap
primary_metric: first tap (empty start), seconds to first meme
guardrails: 
unit: user
variants: none (pre/post)
started: 2026-09-07
check_on: 2026-09-14
decided: 2026-10-30
result: p50 to first meme 11.6 s to 2.8 s; first tap flat (H10 control 60.0% vs ~61.5% pre)
learning: A faster first meme alone does not raise first tap; kept as UX debt removal
code: src/tgbot/handlers/onboarding.py
readout: docs/analyst/onboarding-funnel.sql
---

# H11 — Drop empty-start 3-2-1 countdown

| Field | Value |
|-------|--------|
| **ID** | `onboarding_skip_countdown_v1` |
| **Status** | **KEEP (neutral) 2026-10-30**: p50 to first meme 11.6 → 2.8 s, first-tap flat |
| **Code** | `src/tgbot/handlers/onboarding.py`, share tap in `reaction.py` |

## Hypothesis

Removing the ~9s 3-2-1 (p50 11.6s to first meme) and sending the first meme
right after welcome raises first-tap. Share path already did this at 0.2s and
converted better; after a share tap we now continue the feed (no second welcome).

Not an A/B — UX debt. Score with H9. Rollback = restore the countdown block.

## Next check

**2026-09-14** empty-start p50 seconds to first meme should drop toward ~1s;
first-tap of empty start vs 61% baseline.
