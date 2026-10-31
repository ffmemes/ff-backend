---
id: first_meme_nudge
status: killed
hypothesis: A nudge with the first delivered meme raises first tap for passive new viewers
primary_metric: first meme reacted within 1h
guardrails: mean per-user LR, return days 1-7
unit: user
variants: control:50,treatment:50
started: 2026-04-28
check_on: 
decided: 2026-10-30
result: first tap 15.8% control vs 16.0% treatment (n 1526/1456); reached-5 +2.1 pp (z~1.8); user LR -3.1 pp; d1-7 return 5.0% vs 5.0%
learning: The nudge did not move first tap; it ran 6 months as an orphan split with no registry entry, so register every split
code: removed 2026-10-30 (git history)
readout: docs/analyst/readouts/2026-10-30-experiment-closure.md
---

# Experiment: First meme nudge (orphan split)

Assigned users on their first delivered meme (feed or broadcast) from 2026-04-28.
It had no registry entry and was found during the 2026-10-30 closure. Window: 48h
from assignment, users assigned more than 2 days ago; return measured on users
assigned more than 8 days ago.

| Metric | Control | Treatment |
|--------|---------|-----------|
| n | 1526 | 1456 |
| First meme reacted within 1h (primary) | 15.8% | 16.0% |
| Any reaction in 48h | 17.5% | 17.5% |
| At least 5 reactions in 48h | 10.7% | 12.8% |
| Mean reactions in 48h | 5.4 | 6.2 |
| Mean per-user LR | 39.2% | 36.1% |
| Return on days 1-7 | 5.0% | 5.0% |

The primary is flat. Reached-5 is up +2.1 pp (z~1.8) but LR is -3.1 pp, so the simpler
variant (no nudge) shipped and the code was removed.

Readout: [2026-10-30 closure](../docs/analyst/readouts/2026-10-30-experiment-closure.md).
