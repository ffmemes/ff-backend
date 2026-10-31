---
id: source_affinity_demote_v1
status: shipped
hypothesis: Soft-demoting sources with ndislikes > nlikes (n>=5) by x0.15 raises feed quality without empty-queue symptoms
primary_metric: weekly like rate
guardrails: sends/day and active users not cliffing, empty-queue alerts
unit: user
variants: none (pre/post, 100%)
started: 2026-08-09
check_on: 2026-08-16
decided: 2026-10-30
result: weekly LR 32.6-36.1% post vs 30.7-33.5% pre, no send-volume cliff
learning: Soft demote of majority-dislike sources is safe (+1-3 pp LR); hard-block was rejected (cuts ~57% of inventory offline)
code: RECOMMENDATION_DEMOTE_*, disliked_source_demote_sql
readout: docs/analyst/source-affinity-demote-guardrails.sql, docs/analyst/dwell-feed-vs-broadcast.sql
---

# H2 — Soft demote majority-dislike sources

| Field | Value |
|-------|--------|
| **ID** | `source_affinity_demote_v1` (config flags, not A/B) |
| **Status** | **shipped default ON** (PR #340). **KEEP 2026-10-30**: no volume cliff, LR +1–3 pp |
| **Shipped** | 2026-08-09 deploy `687fd46a` |
| **Code** | `RECOMMENDATION_DEMOTE_*`, `disliked_source_demote_sql` |
| **SQL** | `docs/analyst/source-affinity-demote-guardrails.sql` + inventory section of `dwell-feed-vs-broadcast.sql` |
| **Baseline** | `docs/analyst/readouts/2026-08-09-dwell-and-source-demote-baseline.md` |

## Hypothesis

Deprioritizing sources with `ndislikes > nlikes` (n≥5) by score ×0.15 increases
feed quality (higher session continuation / slightly higher LR on demotable
traffic) **without** increasing empty-queue symptoms, unlike hard-block (~57%
inventory cut offline).

## Decision rules (day-7)

**Keep ON** if:

1. Sends/day and active users not cliffing vs week before deploy;
2. Global like rate not down &gt;3 pp vs pre-deploy 7d window;
3. No spike in empty-queue alerts (Sentry/logs: `has empty meme queue`).

**Tune** multiplier (0.15 → 0.3) if LR up but users complain of “same sources”.  
**Disable** (`RECOMMENDATION_DEMOTE_DISLIKED_SOURCES=false`) if empty-queue or
volume collapse.

## Next check

- **2026-08-12** smoke volume/LR  
- **2026-08-16** full guardrails vs baseline

Rejected: hard-block majority-dislike sources as the default (opt-in flag only).
