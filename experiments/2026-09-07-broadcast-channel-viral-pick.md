---
id: broadcast_channel_viral_pick
status: killed
hypothesis: A meme the channel audience already forwarded is a better single push than the bot-internal HQ pick
primary_metric: react_within_1h % vs HQ
guardrails: LR on reacted rows not -3 pp, viral share of broadcasts >=10%
unit: user
variants: none (viral vs HQ labels, not randomized)
started: 2026-09-07
check_on: 2026-09-08
decided: 2026-10-30
result: pooled react<1h 26.9% vs HQ 36.5% (-9.6 pp); within-user (67) +6.9 pp at 1h but -5.4 pp LR; viral LR 5-20 pp below HQ in every stratum
learning: Channel forwards do not make a better personal push; HQ affinity x LR wins on like rate
code: BROADCAST_CHANNEL_VIRAL_PICK_ENABLED=false (code path kept), src/recommendations/broadcast_pick.py
readout: docs/analyst/broadcast-reengagement.sql
---

# H3c — Channel-viral memes for retention broadcasts

| Field | Value |
|-------|--------|
| **ID** | `broadcast_channel_viral_pick` |
| **Status** | **disabled 2026-10-30** (default `false`; code path kept). Frozen rule trips (1h −9.6 pp vs HQ); arms reach different audiences; within users viral +6.9 pp at 1h but −5.4 pp LR, so HQ is the default (PR #366) |
| **Code** | `src/recommendations/broadcast_pick.py`, kill switch `BROADCAST_CHANNEL_VIRAL_PICK_ENABLED` |
| **Labels** | `broadcast_channel_viral` vs `broadcast_reengagement_hq` vs queue |
| **SQL** | `docs/analyst/broadcast-reengagement.sql` |

## Hypothesis

A meme that the channel audience already forwarded is a better single push than
bot-internal HQ (affinity × like rate), because forwards are a community check
that the joke is worth sending onward.

## Rules

- Last 7 days of `tgchannelru` / `tgchannelen` posts, at least 24h old, ranked
  by latest snapshot forwards. Unseen, matching language, image, `published`.
- Skip known channel members (they already got the channel push).
- Skip `channel_hits_v1` assignees until exposure ends (feed test stays clean).
- Empty pool → existing HQ → queue. Never skip a user because viral is empty.

**Keep ON** if `broadcast_channel_viral` react_within_1h ≥ HQ (same 14d window)
without a like-rate drop >3 pp on reacted rows.

**Disable** (`BROADCAST_CHANNEL_VIRAL_PICK_ENABLED=false`) if viral share of
broadcasts is <10% (always empty) or 1h reactivation is worse than HQ by >5 pp
with ≥200 viral sends.

## Decision 2026-10-30: disable, HQ is default

Sep 10 → Oct 28 stratified readout: viral like rate 5–20 pp below HQ in every
stratum, react-within-1h/24h equal or worse, session length and 7d activity
equal (within-user too). Disable rule met → `BROADCAST_CHANNEL_VIRAL_PICK_ENABLED`
defaults to `false`. Follow-up: `2026-10-30-broadcast-cadence-holdout.md`.

## One-shot idle blast (2026-09-07)

`scripts/broadcast_dormant.py` (removed 2026-10-30; in git history) id `dormant-channel-viral-2026-09-07`.
**Let it finish.** Next extra wave: 7–28d + holdout, not 90d+ never-reacted.
Readout: `docs/analyst/readouts/2026-09-07-onboarding-and-dormant-blast.md`.

## Cadence doctrine (founder 2026-09-07)

Keep **15m / 24h / 48h / 1w / 2w / 4w** while the user is still fresh.
After that, **one monthly** reminder for people who already reacted.
Lever inside the cadence is meme quality (H3c), not fewer early nudges.

2026-10-30: cadence targeting now requires a real reaction near the step
window; per-step no-push holdouts (`broadcast_cadence_holdout_v1_*`) and the
monthly reminder (`monthly_reminder_v1`, flag-gated) are live — see
`2026-10-30-broadcast-cadence-holdout.md`.

Rejected 2026-09-07: killing the 15m-4w reengagement cadence (habit while fresh; monthly after).
Follow-ups: [broadcast_cadence_holdout_v1](2026-10-30-broadcast-cadence-holdout.md), [monthly_reminder_v1](2026-10-30-monthly-reminder.md).
