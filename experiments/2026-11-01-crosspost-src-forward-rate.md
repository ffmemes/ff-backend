---
id: crosspost_src_fwd_v5f
status: running
hypothesis: Memes whose source post was forwarded more than usual for that source get more forwards in our channels
primary_metric: RU Spearman gain rho_v5f - rho_v5 with 95% CI excluding 0
guardrails: coverage_pct >=50%
unit: channel_post
variants: shadow (logged only, score_v5f)
started: 2026-10-31
check_on: 2026-11-28
decided: 
result: unknown
learning: 
code: meme_raw_telegram.forwards, Collect Channel Stats flow, src/crossposting/scoring.py
readout: docs/analyst/crossposting-src-fwd-shadow.sql
---

# Experiment: Crosspost source forward rate (v5f shadow)

- **Created:** 2026-11-01
- **Status:** active, shadow only. Source-post forwards are collected and a shadow score is logged; the production pick is unchanged.
- **Channels:** `tgchannelru` decides. `tgchannelen` is logged for reference.
- **Check date:** **2026-11-28**
- **Shadow readout:** [`docs/analyst/crossposting-src-fwd-shadow.sql`](../docs/analyst/crossposting-src-fwd-shadow.sql)

## Evidence (2026-10-31, offline)

One Telethon read of 4,723 source posts across 102 source channels (0 FloodWait).
The within-source percentile of the source post's forwards / views predicts the forwards
of our crosspost of the same meme:

| predictor vs our crosspost zf | RU Spearman [95% CI] | EN Spearman |
|---|---|---|
| src forward-rate percentile | +0.52 [0.45, 0.58] | +0.28 |
| current v4 score | ≈ 0.01 | |
| content-tag shadow (v5c) | 0.24 | |

Forward rate read at ~24h vs the final rate: Spearman 0.89–0.93, so one read at
~20–48h is enough.

## Hypothesis

Memes whose source post was forwarded more than usual for that source get more forwards
in our channels. Weighting the v5 shadow score by that percentile should raise forwards
per post.

## What shipped

- `meme_raw_telegram.forwards` and `stats_fetched_at` (nullable).
- The 6h `Collect Channel Stats` flow reads views/forwards once per source post aged
  20–48h, in the same Telethon session as the channel sweep: ≤100 ids per call, ≤120
  channels and ≤240s per run, 1s between channels. A FloodWait over 30s stops the batch.
  Resolved channel peers are cached in `meme_source.data.tg_peer`. `views` is overwritten
  with the Telethon value (the HTML parser may overwrite it again while the post is still
  on the channel's first page).
- Each candidate in `crossposting_decision_log.candidates[]` (RU and EN) gets:
  - `src_fwd_pct`: PERCENT_RANK of forwards/views among the source's posts with a read in
    the last 30 days. NULL when the post has no read or the source has fewer than 10;
  - `score_v5f = score_v5 * (0.5 + src_fwd_pct)`, multiplier 1.0 when NULL;
  - `shadow_v5f_rank` and `shadow_v5f_pick_meme_id`.

## Decision rule (frozen 2026-11-01)

Run `crossposting-src-fwd-shadow.sql` on 2026-11-28 and bootstrap the Spearman gain
(`rho_v5f − rho_v5`) over RU posted picks.

| Outcome | Action |
|---------|--------|
| RU gain > 0 and its 95% CI excludes 0 | Switch the RU pick to v5f as an alternate-day A/B against the current ranker, then keep/kill on forwards per post |
| Gain ≈ 0 or CI includes 0 with `coverage_pct` ≥ 50% | Kill: remove the v5f fields; keep the collector only if another signal needs it |
| `coverage_pct` < 50% | Fix coverage first (collector budget, failed sources), extend 2 weeks |

## Metrics after

_(fill on 2026-11-28)_

## Log
- 2026-11-01: scoring refactor: every crosspost score now lives in
  `src/crossposting/scoring.py` (`FACTORS`, `SCORES`, `LIVE`). Promote this shadow =
  set `LIVE[channel]` to `"v5f"` (score_version 7); readouts unchanged, new rows
  also carry `factors`, `scores`, `ranks`, `picks`, `picked_by` dicts. Caveat (unchanged):
  shadow scores rank only the production top-5 (`PRESELECT`), not the whole pool.
  Replay before/after: same pick and top-5 on 120 local fixture runs, the last 40 prod
  decisions and the current prod pool (both channels).
