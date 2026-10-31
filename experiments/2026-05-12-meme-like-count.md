---
id: meme_like_count
status: killed
hypothesis: Showing a meme's like count on the like button (social proof) raises engagement vs a plain heart
primary_metric: mean per-user LR (14d)
guardrails: reaction rate, active days
unit: user
variants: control:50,treatment:50
started: 2026-05-12
check_on: 
decided: 2026-10-30
result: user LR 45.59% vs 46.20%, reaction rate 83.40% vs 83.26%, active days/14d 0.85 vs 0.86 (n 6306/6208)
learning: Like counts on the button do not change engagement; a plain heart is simpler and avoids popularity bias
code: removed 2026-10-30 (git history)
readout: docs/analyst/readouts/2026-10-30-experiment-closure.md
---

# Experiment: Meme like count (orphan split)

Every user was assigned on their first delivery after 2026-05-12. It had no registry
entry and was found during the 2026-10-30 closure. Window: 14d from assignment,
non-broadcast sends, users assigned more than 15 days ago.

| Metric | Control | Treatment |
|--------|---------|-----------|
| n | 6306 | 6208 |
| Users with at least 10 reactions | 507 | 496 |
| Mean per-user LR (primary) | 45.59% | 46.20% |
| Mean per-user LR (>=10 reactions) | 46.03% | 46.13% |
| Mean reaction rate (>=10 sends) | 83.40% | 83.26% |
| Mean reactions in 14d | 30.2 | 33.9 |
| Median reactions (active users) | 27 | 29 |
| Mean active days in 14d | 0.85 | 0.86 |

Flat on LR, reaction rate and activity; the mean-reactions gap is driven by heavy
users. Control (plain heart) shipped and the code was removed.

Readout: [2026-10-30 closure](../docs/analyst/readouts/2026-10-30-experiment-closure.md).
