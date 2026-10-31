---
id: crosspost_v5_shadow
status: running
hypothesis: v5 score (source Beta hit rate x user taste, x like volume on RU) tracks channel virality better than v4
primary_metric: corr(score_v5, zf) - corr(v4, zf) >= 0.05 on posted picks, per channel
guardrails: n_posted >= 60 per channel
unit: channel_post
variants: shadow (logged only, v5_src_beta_taste_v1)
started: 2026-10-30
check_on: 2026-11-14
decided: 
result: unknown
learning: 
code: src/crossposting/scoring.py
readout: docs/analyst/crossposting-v5-shadow.sql
---

# Experiment: Crosspost v5 shadow score (RU + EN)

Created: 2026-10-30
Status: **active (shadow only, production pick unchanged)**
Channels: `tgchannelru`, `tgchannelen`
Check date: **2026-11-14**
Readout: [`docs/analyst/crossposting-v5-shadow.sql`](../docs/analyst/crossposting-v5-shadow.sql)

## Evidence (DS study 2026-10-30)

Walk-forward on image posts (RU n=3,757, EN n=3,818). Target
`zf = log1p(forwards) − channel×week mean`; hit = top quartile of zf within its
week, posts ≥48h old (p̄≈0.26).

- RU best: `ln(nlikes+1) × source Beta hit-rate`, +0.054 top-20% lift over v4 (2/3 folds).
- EN: like volume hurts; learned per-user taste weights strongest, +0.46 over v4 (3/3 folds).
- H7 (top-50 taste cohort) and H8 (`v4_x_src_v1` shadow) **killed**: corr ≈ 0 / −0.09.
  Their code and decision-log fields are removed in this change.
- Frequency: keep ≥5/day. Catch-up bursts (5–6 posts in one hour, ~14 days) hurt
  the 21 MSK slot. Scheduled flows now skip a run if the channel posted <60 min ago.

## Hypothesis

Logging v5 next to v4 for two weeks will show v5 tracks channel virality better than v4:
`corr(score_v5, zf) − corr(v4 final_score, zf) ≥ 0.05` on posted picks.

```
theta_src    = clip((hits_s + 4·p̄) / (n_s + 4) / p̄, 0.5, 2)     # Beta posterior / p̄
w_user       = Σ zf(liked posts, liked before posting) / (n + 20)
user_taste_z = Σ w(likers) / n_likes / stddev(w)
RU score_v5  = ln(nlikes+1) · theta_src · exp(0.5 · user_taste_z)
EN score_v5  = theta_src · exp(user_taste_z)
```

Logged per candidate in `crossposting_decision_log.candidates[]`: `theta_src`,
`user_taste_z`, `score_v5`, `shadow_v5_rank`, `shadow_v5_pick_meme_id`
(`shadow_version = v5_src_beta_taste_v1` until the 2026-10-31 scoring refactor).

## Online vs offline differences (known limits)

- `forwards` is `crossposting.forwards` (latest Telethon snapshot, frozen once the post
  leaves the 30d sweep), the same field the study used. It is not a strict 24h snapshot.
- Labels use the last 365 days of posts. User weights use only likes sent in the last
  90 days, because prod has no valid `meme_id`-leading index on `user_meme_reaction`.
  This keeps the query at ~1.3 s per decision. User coverage is thinner than offline
  (~450 RU / ~300 EN weighted users).

## Decision rule (frozen 2026-10-30)

Run the readout on **2026-11-14** for each channel separately:

| Channel | Canary v5 if | Otherwise |
|---------|--------------|-----------|
| RU | `corr_v5 − corr_v4 ≥ 0.05` with `n_posted ≥ 60` | keep v4, drop v5 shadow or widen likes window |
| EN | `corr_v5 − corr_v4 ≥ 0.05` with `n_posted ≥ 60` | keep v2, drop v5 shadow or widen likes window |

If `n_posted < 60`, extend to 2026-11-21 and do not change the rule.
Also report the disagreement rate and `zf_v5_pick_disagree` against `zf_prod_disagree`.
Counterfactual zf exists only for v5 picks that got posted later.

## Metrics after

_(fill on 2026-11-14)_

## Log
- 2026-10-31: scoring refactor: every crosspost score now lives in
  `src/crossposting/scoring.py` (`FACTORS`, `SCORES`, `LIVE`). Promote this shadow =
  set `LIVE[channel]` to `"v5"` (score_version 5); readouts unchanged, new rows
  also carry `factors`, `scores`, `ranks`, `picks`, `picked_by` dicts. Caveat (unchanged):
  shadow scores rank only the production top-5 (`PRESELECT`), not the whole pool.
  Replay before/after: same pick and top-5 on 120 local fixture runs, the last 40 prod
  decisions and the current prod pool (both channels).
