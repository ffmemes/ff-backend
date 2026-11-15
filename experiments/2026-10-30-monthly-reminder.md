---
id: monthly_reminder_v1
status: running
hypothesis: One monthly HQ meme raises 30d activity of idle users who reacted before by >=3 pp at <2% blocks
primary_metric: react_30d_pct treated - holdout
guardrails: blocked_30d_pct treated <2%
unit: user
variants: treatment:50,holdout:50
started: 2026-10-31
check_on: 2026-11-28
decided: 
result: unknown
learning: 
code: MONTHLY_REMINDER_ENABLED (true in prod, verified 2026-10-31), MONTHLY_REMINDER_HOLDOUT_PCT, broadcast_monthly_reminder flow
readout: docs/analyst/broadcast-holdout-v1.sql
---

# Experiment: Monthly reminder v1

Code shipped 2026-10-30 (PR #366) with
[broadcast_cadence_holdout_v1](2026-10-30-broadcast-cadence-holdout.md); the full
design and decision rules are in that file. The flow runs on the 1st of the month
at 13:00 MSK only once `MONTHLY_REMINDER_ENABLED=true` (default false, the owner flips
it after deploy). When the flag goes on: set `status: running` and `started:`.

- Audience: `user_stats.last_reaction_at` 29-365 days ago, not blocked (1,859 users on
  2026-10-30, so about 930 pushed). One HQ meme via `send_meme_broadcast`,
  `broadcast_id = monthly-reminder-YYYY-MM`.
- Holdout 50% (`MONTHLY_REMINDER_HOLDOUT_PCT`), kept on until the readout so the 30d
  window stays clean.
- Prior evidence: the 2026-09-07 dormant blast brought about +110 returns in 24h,
  about 95 still active a month later, about 20 blocks.

## Decision rule (frozen 2026-10-30)

Keep if `react_30d_pct` treated - holdout >= +3 pp and `blocked_30d_pct` treated < 2%,
then set `MONTHLY_REMINDER_HOLDOUT_PCT=0`. Otherwise set `MONTHLY_REMINDER_ENABLED=false`.
Fewer than 150 users per arm: extend 2 weeks.

## Log
- 2026-10-30: code merged, flag off.

- 2026-10-31: verified MONTHLY_REMINDER_ENABLED=true in the prod Prefect runner; status set to running (started = date verified, first send follows the flow schedule).


## Readout 2026-11-15

Interim: D7 reactors treatment 69/941 vs holdout 8/925 (+6.47 pp, 95% CI +4.75..+8.36); D14 85/941 vs16/925. Currently blocked 21/941=2.23% vs1/925, above treatment <2% point gate. No closed D30 windows; Dec11 decision unchanged. [Full snapshot](../docs/analyst/readouts/2026-11-15-experiment-review.md).

## Operational checkpoint 2026-11-28

Decide whether to suppress the next Dec1 send before it runs: the current block
share already exceeds the 2% gate, and the first D30 window finishes around the
next scheduled send. The next checkpoint moves to Nov28 to make that decision
visible; final D30 evaluation remains Dec11. Do not expand exposure or remove the
holdout on the interim reactivation win. Runtime flags and schedules have not
been changed by this review; suppressing a send requires an explicit operational
change and verification, not merely changing this record.
