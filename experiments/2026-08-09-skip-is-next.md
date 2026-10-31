---
id: skip_is_next_not_ban
status: shipped
hypothesis: The dislike button is mostly 'next'; ranking should prefer likes + dwell, not treat skips as bans
primary_metric: sec_to_react: skip vs like
guardrails: 
unit: user
variants: none (measurement contract)
started: 2026-08-09
check_on: 
decided: 2026-08-09
result: skip p50 4.7 s vs like 7.1 s; instant skip 19% vs like 9% (7d feed)
learning: Treat skip as next, not dislike; no dwell-weight ship without an offline counterfactual
code: 
readout: docs/analyst/dwell-feed-vs-broadcast.sql
---

# H4 — Skip ≠ hate (measurement contract, not a ship)

| Field | Value |
|-------|--------|
| **ID** | `skip_is_next_not_ban` |
| **Status** | **accepted product doctrine** |
| **Evidence** | skip p50 4.7s vs like 7.1s; instant skip 19% vs like 9% (7d feed) |
| **SQL** | `docs/analyst/dwell-feed-vs-broadcast.sql` |

## Hypothesis (ongoing)

Dislike button is primarily “next”; ranking must prefer **likes + dwell**, not
raw skip counts as bans. Future work: down-weight `sec_to_react < 2s` skips and
ignore `>1h` reactions in affinity.

## Next check

- **2026-08-16** re-run dwell percentiles; compare to baseline readout  
- No ship decision until a dedicated dwell-weight PR with offline counterfactual
