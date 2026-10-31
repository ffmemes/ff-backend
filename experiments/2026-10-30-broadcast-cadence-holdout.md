---
id: broadcast_cadence_holdout_v1
status: running
hypothesis: The 15m push mostly re-times sessions heavy users would start anyway; later steps (24h, 1w, 2w, 4w) bring back lapsing users
primary_metric: reactions/user/week (15m, 24h); active d7-14 (1w, 2w, 4w)
guardrails: blocks <1%, weekly-reactor % not lower in holdout, >=150 users/arm
unit: user
variants: push:85,holdout:15 (15m, 24h); push:80,holdout:20 (1w, 2w, 4w)
started: 2026-10-30
check_on: 2026-11-20
decided: 
result: unknown
learning: 
code: BROADCAST_CADENCE_HOLDOUT_ENABLED, broadcast_cadence_holdout_v1_<step>
readout: docs/analyst/broadcast-holdout-v1.sql
---

# Experiment: Broadcast cadence holdout + monthly reminder

Created: 2026-10-30  
Status: active  
Owner: engineer / analyst  
Deployed: pending (holdout starts on deploy; monthly reminder waits for `MONTHLY_REMINDER_ENABLED=true`)  
**Check 1: 2026-11-20** (15m / 24h)  
**Check 2: 2026-12-11** (1w / 2w / 4w, monthly reminder)  
SQL: [`docs/analyst/broadcast-holdout-v1.sql`](../docs/analyst/broadcast-holdout-v1.sql)  
Background: [broadcast_channel_viral_pick](2026-09-07-broadcast-channel-viral-pick.md) (H3c, cadence doctrine). Monthly reminder has its own record: [monthly_reminder_v1](2026-10-30-monthly-reminder.md)

## Why

Readout 2026-10-30 (prod, sends Aug 15 → Oct 28): every cadence step is
net-positive on returns vs blocks, but no step was ever held out. 15m is 61% of
push volume and goes to about 1.1k heavy users, so its causal value is unknown.
The founder's monthly reminder for idle users who reacted before was never
deployed. Evidence from the 2026-09-07 blast suggests a first run brings about
+110 returns in 24h, with about 95 still active a month later and about 20 blocks.

## Changes shipped with this note

1. **Targeting:** cadence steps also require a real reaction no earlier than
   `step window + 60 min` ago. `last_active_at` moves without reactions, so
   users with no reaction in 40+ days kept getting pushes (85 blocks/1k).
2. **Pick:** `BROADCAST_CHANNEL_VIRAL_PICK_ENABLED` defaults to false, so HQ is
   the push meme (H3c disable rule: viral like rate is 5–20 pp lower and
   reactions are equal or worse).
3. **Cadence holdout** `broadcast_cadence_holdout_v1_<step>`: users are split by
   `sha256(experiment_id:user_id) % 100 < pct`. A holdout user is selected but
   gets no push. The holdout is 15% for 15m and 24h and 20% for 1w, 2w and 4w.
   48h has no holdout. Each step is randomized independently. The first
   selection is logged in `experiment_assignment`. Kill switch:
   `BROADCAST_CADENCE_HOLDOUT_ENABLED`.
4. **Monthly reminder** `monthly_reminder_v1`: the
   `broadcast_monthly_reminder` flow runs on the 1st of the month at 13:00 MSK.
   It targets users with `user_stats.last_reaction_at` 29–365 days ago who are
   not blocked. Each user gets one HQ meme via `send_meme_broadcast`, with
   `broadcast_id = monthly-reminder-YYYY-MM`. The holdout is 50%
   (`MONTHLY_REMINDER_HOLDOUT_PCT`) and stays on until readout, so the 30-day
   window stays clean. Audience on 2026-10-30: 1,859 users, so about 930 are
   pushed.

## Hypotheses

- **H-15m:** the 15m push mostly re-times sessions heavy users would start
  anyway. In that case the holdout keeps ≥97% of treated reactions/user/week.
- **H-24h, 1w, 2w, 4w:** later steps bring back users who would otherwise lapse
  (treated > holdout on weekly-reactor % and active d7–14).
- **H-monthly:** one monthly HQ meme raises 30d activity of idle users who
  reacted before by ≥3 pp at <2% blocks.

## Decision rules

- **Cut 15m** if, after 3 weeks (2026-11-20), holdout reactions/user/week is at
  least treated − 3%. Apply the same test to 24h, but cut only if
  weekly-reactor % is also not lower in the holdout.
- **1w / 2w / 4w** (2026-12-11): keep a step if treated − holdout active d7–14
  is > 0 and blocks are < 1%. Otherwise drop it.
- **Monthly reminder** (2026-12-11, after the first run's 30d window closes):
  keep it if `react_30d_pct` treated − holdout is ≥ +3 pp and
  `blocked_30d_pct` treated is < 2%. Then set `MONTHLY_REMINDER_HOLDOUT_PCT=0`.
  Otherwise set `MONTHLY_REMINDER_ENABLED=false`.
- If samples are too small (< 150 users per arm), extend 2 weeks rather than
  decide.

## Notes

- The readout is intent-to-treat by first assignment. Holdout users still
  receive the other steps, which is shared background for both arms.
- Holdout skips are not stored as `user_meme_reaction` rows. Use the
  assignment table for denominators.
