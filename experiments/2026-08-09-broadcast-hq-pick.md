---
id: broadcast_reengagement_hq_pick
status: shipped
hypothesis: Picking the push meme by user x source affinity x raw like rate beats a blind queue pop on react-within-1h
primary_metric: react_within_1h %
guardrails: LR not -5 pp vs fallback, fallback share <80%
unit: user
variants: none (HQ pick vs queue fallback labels, not randomized)
started: 2026-08-09
check_on: 2026-08-16
decided: 2026-10-30
result: 14d: 5,533 sends, LR 57.2%, react<1h 36.5%, queue fallback 0.4% (pre-HQ LR ~54%, n~39)
learning: Affinity x like-rate is a solid default push meme
code: BROADCAST_HIGH_QUALITY_PICK_ENABLED, src/recommendations/broadcast_pick.py
readout: docs/analyst/broadcast-reengagement.sql
---

# H3b — High-quality meme pick for retention broadcasts

| Field | Value |
|-------|--------|
| **ID** | `broadcast_reengagement_hq_pick` |
| **Status** | **KEEP 2026-10-30**: 14d LR 57.2%, react<1h 36.5%, queue fallback 0.4% |
| **Code** | `src/recommendations/broadcast_pick.py`, kill switch `BROADCAST_HIGH_QUALITY_PICK_ENABLED` |
| **Labels** | `broadcast_reengagement_hq` (SQL pick) vs `broadcast_reengagement` (queue fallback) |
| **SQL** | `docs/analyst/broadcast-reengagement.sql` |

## Hypothesis

Choosing the reengagement meme by **user×source affinity × raw like rate**
(avoiding majority-dislike sources) beats blind feed-queue pop on:

1. **react_within_1h %** (primary — “came back because of this push”)
2. like rate among reacted
3. p50 `sec_to_react` among in-window reactions (secondary)

## Pre-HQ baseline (2026-08-09, ~39 `broadcast_reengagement` sends)

- like rate ~54% (small n)
- only ~4 reacts under 2 minutes — delayed open is the norm

## Decision rules (day-7 from HQ deploy)

**Keep HQ ON** if:

- `broadcast_reengagement_hq` react_within_1h ≥ queue-fallback **or** ≥ pre-HQ baseline + directionally better LR;
- no send failure spike (empty HQ → fallback should keep volume).

**Disable** (`BROADCAST_HIGH_QUALITY_PICK_ENABLED=false`) if HQ pool empty for
most users (fallback rate &gt;80%) or LR collapses &gt;5 pp vs fallback.

## Next check

- **2026-08-12** smoke: any `_hq` rows? fallback share?  
- **2026-08-16** primary HQ vs fallback vs feed
