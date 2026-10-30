# Experiment: Explore budget v1 (labeling budget + fresh-viral + idle-return slot)

Created: 2026-10-30
Status: active
Owner: engineer / analyst
Deployed: pending (first `explore_budget_v1` assignment row = start)
Measure after: 2026-11-20

## Hypothesis

Moderators are super-users and should not be stuck on a worse feed. They get
`low_sent_pool` in 75% of batches today: 256k sends in 30d at LR 0.24–0.32,
against 0.31–0.42 from other engines for the same users. 40% of those sends go
to memes that are 180–360 days old at their 21st+ send, and 75% go to sources
the user mostly dislikes. That is far more than labeling needs: about 390 fresh
RU+EN memes/day × ~10 reactions ≈ 3.9k labels/day, while low_sent delivers
about 8.5k/day. Meanwhile regular users rarely see fresh winners. Early LR
predicts later LR: first-20 LR ≥ 0.50 means later regular-user LR 0.46 vs a
0.436 baseline, and < 0.40 means 0.355. Sessions die on the first feed meme
after a push (23% abandon). That slot is lr_smoothed today; warm-queue
engines abandon 11–15% there.

Spending exploration only where it labels fresh memes, while showing proven
fresh winners to everyone, should raise likes per active user and memes per
session without starving labeling.

## Changes Made (treatment only)

1. **Labeling budget**: moderator low_sent quota is 50% instead of 75%
   (`feed_turn.planner.low_sent_quota`). `low_sent_pool` serves only memes
   < 7d old with < 20 reactions. It early-stops when smoothed LR
   `(likes+1)/(reactions+2)` < 0.25 after ≥ 10 reactions, and orders the user's
   disliked sources last (`RECOMMENDATION_DEMOTE_*`). An unfilled quota falls
   through to the normal blend, which is existing behavior.
2. **Fresh-viral**: `fresh_viral` engine (`like_spread_and_recent_memes(fresh_viral=True)`)
   serves memes < 72h old with ≥ 20 reactions and raw LR ≥ 0.50. It takes 15%
   of the mature blend mass, with other engines scaled ×0.85. All blend engines
   drop fresh memes (< 7d) with ≥ 20 reactions and LR < 0.40.
3. **Idle-return first slot**: with an empty queue, the first meme comes from
   `like_spread_and_recent_memes` instead of `lr_smoothed`. The queue's Redis TTL
   is 1h, so an empty queue means the user was idle > 1h or arrived from a
   push. Moderators get that meme before their labeling memes. Known noise:
   the TTL restarts on every refill, and the queue can also be empty mid-session
   (a refill still in flight). If the push itself falls back to the queue, it
   takes this slot.
4. Migration `ix_meme_ok_created_at` (partial `meme(created_at) WHERE status='ok'`)
   keeps the fresh-window queries well under 300 ms per user (see Latency).

Code: `src/recommendations/pipeline.py`, `candidates.py`, `blender_experiments.py`,
`meme_queue.py`, `src/feed_turn/planner.py`.

## Assignment

- Eligible: users at batch build with `nmemes_sent ≥ 30`. Cold start is untouched.
- Split: `sha256("explore_budget_v1:" + user_id) % 2`, persisted in
  `experiment_assignment` on the first eligible batch (variant `control` / `treatment`).
- Kill switch: `EXPLORE_BUDGET_V1_ENABLED=false`, which serves everyone the control feed.
  Assignment rows stay readable.

## Decision rule (check 2026-11-20)

Readout: `docs/analyst/explore-budget-v1.sql` (one SELECT, read-only). Read it per
segment (`mod` / `user`), with per-user means over feed sends only (broadcasts excluded).

**Primary**
- `likes_per_user_week` (likes per active user per week)
- `memes_per_session` (30-min gap sessions)

**Guardrails**
- `fresh_ru_labeled_share` ≥ 0.90: RU ok memes reach ≥ 10 reactions within 7d.
  Baseline 1.000 on 2026-10-30, with n = 2251 memes created 14..7d ago. This is
  global, not per arm, and only reflects the experiment from about day 14.
- Empty-queue errors: Sentry/logs `recommendation batch diagnostics` with
  `selected_count = 0` or `last_resort_used = true` must not rise vs pre-deploy.
- `pos2_abandon` (first feed meme after a reacted push, no reaction ≤ 30 min)
  must be ≤ control.

**Ship** (treatment becomes default, experiment code collapses) if both primaries
are ≥ control in both segments, at least one is up ≥ 3% relative, and every
guardrail holds.
**Kill** (set the kill switch, then remove the code) if any guardrail breaks or both
primaries are down. Otherwise **hold** to 2026-12-04. If only the labeling
guardrail breaks, raise the moderator quota back toward 75% before killing.

## Latency (prod EXPLAIN ANALYZE, 2026-10-30, heaviest 3-language moderator)

| query | before index | index-equivalent plan |
|---|---|---|
| low_sent control (current prod) | 3,581 ms | (unchanged) |
| low_sent treatment | 441 ms | 97 ms |
| fresh_viral | 365 ms | 57 ms |
| bad-fresh filter (90 ids, PK) | 1.6 ms | 1.6 ms |

"Index-equivalent" bounds `meme.id` to the 7d / 72h range, which is the same
range scan the new partial index provides.

## Metrics Before / After

| Window | users C/T (mod) | users C/T (user) | likes/user/wk C/T | memes/session C/T | pos2 abandon C/T | fresh RU labeled | Decision |
|---|---|---|---|---|---|---|---|
| 2026-11-06 smoke | | | | | | | |
| 2026-11-20 | | | | | | | |

## Conclusion

_Filled on completion only._
