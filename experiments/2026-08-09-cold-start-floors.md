---
id: cold_start_first_impression_v2
status: shipped
hypothesis: Raising cold_start_explore floors (raw LR >=0.50, >=25 reactions) and best_uploaded in CS3 lifts first-10 LR and reached-10
primary_metric: first tap, first-10 LR
guardrails: no empty-queue spike for new users, CS3 continuation
unit: user
variants: none (pre/post)
started: 2026-08-09
check_on: 2026-08-16
decided: 2026-10-30
result: first tap 61.5% to 62.0% (n=100 post), underpowered; no rollback trigger
learning: Stricter quality floors did not measurably move first tap; kept as harmless
code: cold_start_explore raw-LR floor, CS3 blend (best_uploaded + text_light)
readout: docs/analyst/metrics.sql
---

# H5 — Cold-start first-session quality floors

| Field | Value |
|-------|--------|
| **ID** | `cold_start_first_impression_v2` |
| **Status** | **KEEP 2026-10-30**: no rollback trigger. First-tap 61.5 → 62.0% (n=100 post), so the lift is unproven |
| **Code** | `cold_start_explore` raw-LR floor; CS3 blend → `best_uploaded` + text-light |
| **SQL** | engine slice in `docs/analyst/metrics.sql` / cold_start quality scripts |

## Hypothesis

**A1.** Raising `cold_start_explore` floors (raw like rate ≥0.50, ≥25 reactions,
order by `lr_smoothed`) lifts first-10 LR and reached-10 vs pre-change
(guarded explore was ~**18%** LR on 7d — too weak for first impression).

**A2.** CS3 (memes 16–29) replacing `like_spread` with `best_uploaded_memes`
improves LR/continuation in that band without starving personalization
(`cold_start_adapt` stays fixed_pos 0).

## Decision rules (day-7)

**Keep** if first-10 LR for `cold_start_explore*` ≥ pre-change + directionally
higher reached-5/10; no empty-queue spike for new users.

**Rollback explore floors** if explore pool empty → fallback share spikes and
session depth drops.

**Rollback CS3** if `best_uploaded` share causes lower continuation vs prior
week CS3 band.

## Next check

- **2026-08-12** smoke: explore volume + LR  
- **2026-08-16** first-10 / CS3 band metrics
