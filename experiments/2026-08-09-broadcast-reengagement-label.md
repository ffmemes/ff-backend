---
id: broadcast_reengagement_label
status: shipped
hypothesis: Labeling retention pushes separately from feed engines lets us measure true in-session sec_to_react
primary_metric: broadcast vs feed p50 sec_to_react
guardrails: 
unit: user
variants: none (labeling)
started: 2026-08-09
check_on: 2026-08-16
decided: 2026-10-30
result: broadcast p50 sec-to-react 3.8-5.5k s vs feed 5.7 s
learning: Push reactions are delayed opens; keep broadcast_* rows out of feed dwell and LR analysis
code: flows/broadcasts/meme.py recommended_by=broadcast_*
readout: docs/analyst/broadcast-reengagement.sql
---

# H3 — Broadcast delivery label for dwell analytics

| Field | Value |
|-------|--------|
| **ID** | `broadcast_reengagement_label` |
| **Status** | **DONE 2026-10-30**: labels live, broadcast p50 sec-to-react 3.8–5.5k s vs feed 5.7 s |
| **Shipped** | 2026-08-09 with #340 |
| **Code** | `flows/broadcasts/meme.py` → `recommended_by=broadcast_*` |
| **SQL** | `docs/analyst/broadcast-reengagement.sql`, dwell SQL |

## Hypothesis

Labeling retention pushes separately from feed engines lets us measure true
in-session `sec_to_react` and optimize broadcast timing for **fast** reaction.

## Success criteria

1. ✅ Labeled rows exist (`broadcast_reengagement` / `_hq`)
2. Broadcast p50 `sec_to_react` **higher** than feed (delayed opens expected)
3. Share of broadcast reactions with `sec_to_react > 1h` documented

## Next check

- **2026-08-12 / 16** — full feed vs broadcast dwell table
