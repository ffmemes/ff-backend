# Experiment closure: 2026-10-30

**Snapshot:** prod DB, read-only SELECTs, about 2026-10-30 16:35 UTC. Aggregates only.
**Registry:** [`docs/growth/HYPOTHESES.md`](../../growth/HYPOTHESES.md), section "Decision log: 2026-10-30".
**Power caveat:** with about 20–35 new users per week, ~10 pp onboarding gaps sit near z≈1.6.
Onboarding tests are decided by their pre-registered directional kill rules, not by
significance. Pooled feed metrics are dominated by 2–3 users with more than 20k sends,
so this readout uses user-level means.

## Splits that were holding traffic

| Experiment | Before | Action in this PR |
|------------|--------|-------------------|
| H10 `cold_start_fresh_viral_v1` | 50/50 on new users | `COLD_START_FRESH_VIRAL_EXPERIMENT_ENABLED` default `False` (the prod env was already set false) |
| H1 `viral_shares_blender_v1` | 50/50 on mature users at day 82 | assignment/weight path deleted, all users get the shipped mature default |
| `first_meme_nudge` | 50/50 on first meme since 2026-04-28 | nudge code removed, everyone gets control |
| `meme_like_count` | 50/50 on every delivery since 2026-05-12 | like-count code removed, everyone gets control (plain heart) |
| `channel_hits_v1` | exposure window ended 2026-09-19 | code default is already `False`. The prod env still has it `true` (harmless, the window is enforced in code) |

## H1 `viral_shares_blender_v1`: KILL

n = 344 control / 350 treatment, 426k / 395k sends.

| Metric | Control | Treatment |
|--------|---------|-----------|
| Unique non-self share clickers | 13 | 10 |
| Clickers per 1k sends (primary) | 0.031 | 0.025 |
| New invites (deduped) | 5 (0.012/1k) | 7 (0.018/1k; one inviter accounts for 4) |
| Mean per-user LR | 49.7% | 47.5% |
| Pooled p50 session | 14 | 10 |
| Median of per-user p50 session | 10 | 10 |
| `viral_shares` share of sends | 0 | 0.76% |

The primary metric fails. The pooled session drop trips the frozen kill trigger, but it
comes from heavy-user composition, since the user-level median is flat.
**SQL bug fixed:** `viral-shares-blender-v1.sql` §4 joined invites on `variant`, which
multiplied invites by cohort size (it reported 1720/2450 instead of 5/7). §3 `share_clicks`
counted LEFT-joined send rows. Both are fixed, and §4 now returns 5/7.

## H10 `cold_start_fresh_viral_v1`: KILL

Users assigned more than 2 days ago: n = 95 control / 99 treatment, measured over 48h,
non-broadcast.

| Metric | Control | Treatment |
|--------|---------|-----------|
| First tap | 60.0% | 48.5% |
| First like in first 10 | 41.1% | 29.3% |
| Reached 5 | 38.9% | 35.4% |
| Reached 10 | 31.6% | 25.3% |
| First-10 LR | 32.6% | 27.0% |
| Blocked within 1h | 19 | 27 |

Both frozen kill conditions fire: first tap went down and block-in-1h went up.

## channel_hits_v1: KILL (inconclusive per protocol)

n = 43 control / 42 treatment hosts, ITT. Exposure was 531 hit rows (2.06% of the
treatment feed). New invitees were 1 vs 4, retained invitees 0 vs 1, and unique non-self
link recipients 1 vs 5. Hosts active in days 7–13 were 79.1% vs 73.8%. Host reactions
vs the 28d baseline were 0.95 vs 0.77. The study needed at least 6 retained guests in
treatment and got 1.

## Shadow signals (crossposting): KILL as signals

- **H7 taste cohort:** top vs bottom half by n_taste gave f1k 28.52 vs 28.72 (n=287 posts with
  n_taste≥1). taste≥1 vs taste=0 gave 28.62 vs 29.87. The pre-registered Δ>0 test fails.
- **H8 `v4_x_src_v1`:** it disagreed with the prod pick 70.9% of the time (275/388).
  corr(shadow, f1k) = −0.092 and corr(prod, f1k) = −0.047 (n=363). Agreed vs disagreed
  picks gave f1k 29.01 vs 29.10.
- The decision_log fields stay in place. A separate crossposting PR is replacing shadow scoring.

## Orphan splits (no registry entry)

### `first_meme_nudge` (since 2026-04-28): KILL, control to 100%

The test assigned users on their first delivered meme (feed or broadcast). Window: 48h
from assignment, only for users assigned more than 2 days ago. Return is measured on
users assigned more than 8 days ago.

| Metric | Control | Treatment |
|--------|---------|-----------|
| n | 1526 | 1456 |
| First meme reacted within 1h (primary) | 15.8% | 16.0% |
| Any reaction in 48h | 17.5% | 17.5% |
| At least 5 reactions in 48h | 10.7% | 12.8% |
| Mean reactions in 48h | 5.4 | 6.2 |
| Mean per-user LR | 39.2% | 36.1% |
| Return on days 1–7 | 5.0% | 5.0% |

The primary metric (first tap, the "passive viewer" target) is flat. Reached-5 is up
+2.1 pp (z≈1.8), but LR is −3.1 pp. That is not clearly better, so the simpler variant
(no nudge) ships.

### `meme_like_count` (since 2026-05-12): KILL, control to 100%

Every user was assigned on their first delivery after launch. Window: 14d from
assignment, non-broadcast sends, only for users assigned more than 15 days ago.

| Metric | Control | Treatment |
|--------|---------|-----------|
| n | 6306 | 6208 |
| Users with at least 10 reactions | 507 | 496 |
| Mean per-user LR (primary) | 45.59% | 46.20% |
| Mean per-user LR (≥10 reactions) | 46.03% | 46.13% |
| Mean reaction rate (≥10 sends) | 83.40% | 83.26% |
| Mean reactions in 14d | 30.2 | 33.9 |
| Median reactions (active users) | 27 | 29 |
| Mean active days in 14d | 0.85 | 0.86 |

The test is flat on LR, reaction rate and activity. The mean-reactions gap is driven by
heavy users. Control (plain heart) is simpler and avoids popularity bias.

`upload_promo_day1` still assigns about 1 user per month. It was out of scope and was left as is.

## Kept / unchanged

| Hypothesis | Decision | Numbers |
|------------|----------|---------|
| H2 source demote | keep 100% | weekly LR 32.6–36.1% post vs 30.7–33.5% pre, no volume cliff |
| H3 broadcast label | done | broadcast p50 sec-to-react 3.8–5.5k s vs feed 5.7 s |
| H3b HQ pick | keep | 14d: 5,533 sends, LR 57.2%, react<1h 36.5%, fallback 0.4% |
| H3c channel-viral pick | unchanged, pending user-randomized readout | pooled 1h 26.9% vs HQ 36.5%. Within-user (67): +6.9 pp 1h, −5.4 pp LR |
| H5 cold-start floors | keep | first-tap 61.5 → 62.0% (n=100 post), underpowered |
| H6 crosspost v4 | keep 100% | hit rate 32.1 → 41.0% (z≈2.4), f1k 26.2 → 28.9, v0 drift +3.4 f1k |
| H11 skip countdown | keep (neutral) | p50 to first meme 11.6 → 2.8 s. First tap: H10 control 60.0% vs ~61.5% pre |
| `ocr_length_preference_v1` | invalid (decided 2026-10-05) | primary +5.78 pp, but late OCR 23.1% vs the 5% limit |

## Other findings

- **`text_light_lr_smoothed` (~20 sends/week) is not a leftover.** Over 28d it had 75 sends,
  split by the user's prior sends as 0–5: 23, 6–15: 15, 16–29: 16, 30–99: 21 (lagging
  `user_stats`). It is the CS3 blend weight plus the cold-start fallback, shipped to everyone
  in #271. The disabled `text_light_blender_v1` overlay (`text_light_blender_v1_enabled=False`)
  does not serve. No change.
- **H9 regression flag:** users who never got a meme rose from 3.1% to 12.6% after 2026-09-07,
  and 25/26 of them have no language row. They drop at the language picker. This is not addressed here.
