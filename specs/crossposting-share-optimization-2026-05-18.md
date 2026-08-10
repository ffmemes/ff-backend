# Crossposting Share Optimization Readout (2026-05-18)

## Why this exists

Future agents should not need to rediscover the Telegram channel share baseline
from scratch. This file is the compact, repo-tracked summary of the May 2026
crossposting analysis. Generated `experiments/` files may be local/ignored.

## Data sources

- `crossposting`: current per-post Telegram channel stats.
- `crossposting_snapshots`: Telethon time-series snapshots, collected every 6h.
- `user_meme_reaction`: bot reactions before channel posting.
- `user_deep_link_log`: in-bot share clicks (`s_...`) and channel deep links
  (`sc_...`).

Read-only prod analysis was run through `ANALYST_DATABASE_URL`.

## Current system

`score_version=2` shipped on 2026-04-28. The ranker in
`src/crossposting/service.py` uses:

- image-only channel posts;
- source-quality multiplier:
  `AVG(forwards * SQRT(GREATEST(views, 1) / 100.0))`;
- one source per channel per 24h diversity cap;
- bot quality floor `meme_stats.nlikes >= 5`;
- `meme_stats.invited_count` boost for in-bot share clicks.

## Main readout

Stats collector was healthy during analysis. Latest observed snapshots were
2026-05-18 05:00 UTC.

All-content comparisons are misleading because the Apr 13 video boost made the
pre-v2 phase video-heavy. Videos had higher forwards per 1k views, but reduced
reach and caused a video-heavy feed. They were later hard-filtered out.

Image-only 24h forward-rate comparison:

| Channel | Phase 1 image avg fwd/1k | Phase 2 v2 image avg fwd/1k | Lift |
| --- | ---: | ---: | ---: |
| RU | 18.34 | 24.97 | +36% |
| EN | 11.88 | 18.98 | +60% |

Image-only 24h views were stable:

- RU: 394.7 -> 406.4 avg views.
- EN: 72.9 -> 77.2 avg views.

Conclusion: v2 improved image post share rate without lowering image reach.

Subscriber counts did not show RU growth:

- RU: 2182 on 2026-04-13 -> 2158 on 2026-05-17.
- EN: 627 on 2026-04-13 -> 654 on 2026-05-17.

Better meme selection alone is not yet enough to grow RU subscribers.

## Superuser-like hypothesis

Hypothesis: likes from a subset of bot users might predict channel forwards even
if all-user likes do not.

Strict offline check:

- target = nearest 24h channel snapshot after posting;
- image posts only;
- only reactions with `reacted_at < crossposting.created_at`;
- train before 2026-05-05, test after 2026-05-05;
- candidate users ranked by train lift:
  `avg(fwd/1k | liked) - avg(fwd/1k | skipped)`.

Result:

| Channel | Test posts | All-likes corr | Top-25 likes corr | Top-25 like-rate corr | Top-25 any-like lift |
| --- | ---: | ---: | ---: | ---: | ---: |
| RU | 81 | -0.117 | -0.023 | 0.155 | 0.98x |
| EN | 70 | -0.228 | -0.170 | -0.182 | 0.98x |

Conclusion: superuser-like signal failed the offline gate. Do not ship it to
online A/B yet. Shadow-log only.

## In-bot share signal

Prior in-bot share clicks before channel posting are a more promising RU signal:

| Channel | Posts | Posts with prior share | Avg fwd/1k | Avg when shared | Lift |
| --- | ---: | ---: | ---: | ---: | ---: |
| RU | 144 | 24 | 23.97 | 27.88 | 1.16x |
| EN | 145 | 39 | 17.45 | 16.38 | 0.94x |

Conclusion: in-bot share clicks are a candidate RU signal. However, the current
ranker uses all-time `meme_stats.invited_count`, which is not timestamp-safe for
offline evaluation and can include clicks after a simulated channel decision.
The next test should compare current v2 against a timestamp-safe prior-share
replacement. Do not copy the RU weight to EN.

## Next experiment gate

Do not launch `score_version=3` immediately. First build an offline evaluator
and shadow score.

Production shadow experiment:

- Name: `crossposting-pre-share-shadow-v1`.
- Hypothesis: for RU, timestamp-safe in-bot share clicks observed before the
  channel decision improve prediction of 24h channel forwards. EN remains
  report-only because the prior offline lift was negative.
- Implementation: keep the live ranker at `score_version=2` and do not change
  selected memes. Add `pre_inbot_share_clicks` and
  `pre_inbot_share_click_users` to `crossposting_decision_log.candidates` for
  the already logged top-N candidates. Count only rows created before the
  decision timestamp and exclude self-clicks where the clicker is also the
  sharer encoded in `s_{sharer_user_id}_{meme_id}`.
- Rollback: revert the logging-only change or ignore the JSON fields. There is
  no schema migration, no score-version bump, and no posting-behavior change.
- First production check: after deploy, trigger one RU and one EN crossposting
  run, then verify their newest decision-log rows contain the two shadow fields.

Offline evaluator requirements:

1. Label channel posts using 24h snapshots.
2. Use only pre-posting bot reactions and share clicks.
3. Split per channel by time: train, validation, test.
4. Include random same-size user subsets as placebo.
5. Compare against all-user likes, all-user like rate, current v2 score, and
   source-only score.
6. Reconstruct source-quality and share features as of the simulated decision
   time; do not use current all-time aggregates when backtesting.

Online A/B is allowed only if the fresh test split shows:

- coverage >= 35% of candidate posts;
- Spearman correlation beats all-likes and all-like-rate by >= 0.05;
- top-20% shadow-ranked posts beat all-likes top-20% lift by >= 15%;
- selected signal beats 95th percentile of random subsets;
- absolute `forwards_24h` and `views_24h` do not drop.

Minimum next experiment: RU-only offline evaluator for a timestamp-safe
prior-share feature, with superuser features measured but coefficient fixed at
zero. EN stays report-only until it shows a positive offline signal.

## Stats collector (2026-08-10)

`collect_channel_stats` (Telethon) is healthy in prod: ~6h cadence, p50 time to
first snapshot ~4.7h. Gaps for early canary reads:

| Path | Schedule | Purpose |
|------|----------|---------|
| Full sweep | `0 */6` LON | 30d messages + subs + lifecycle |
| Young posts | `30 * * * *` LON | posts &lt;48h only (dense early curve) |
| Post-hook | after each TG crosspost | first sample within seconds |

Shared write path: `_persist_crosspost_metrics` → `crossposting_snapshots` +
live `crossposting.views/forwards`. Single-msg API:
`refresh_crosspost_message_stats(channel, message_id, meme_id)`.

## Architecture follow-up

The current ranker SQL and analysis queries are too expensive to rediscover and
too easy to subtly change. High-leverage follow-ups:

- Create a channel outcome labeling Module for 24h/48h snapshots.
- Create a pre-posting signal Module for likes, like rates, in-bot share clicks,
  and future predictor-user weights. Its Interface must accept `posted_at` and
  guarantee no post-after-post leakage.
- Keep the hot crossposting ranker from computing predictor users inline.
  Materialize predictor weights separately if the offline gate passes.
- Add an index before routine evaluator work:

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS
  ix_user_meme_reaction_meme_id_reacted_at
ON user_meme_reaction (meme_id, reacted_at)
INCLUDE (user_id, reaction_id, sent_at);
```

## May 21 recheck

Prod snapshots were fresh through 2026-05-21 11:00 UTC. The v2 ranker did not
show a clear forward-rate regression:

| Channel | Recent mature image posts | Recent agg fwd/1k | v2 agg fwd/1k |
| --- | ---: | ---: | ---: |
| RU | 43 | 23.57 | 24.59 |
| EN | 39 | 18.65 | 18.42 |

Subscriber growth is the unsolved part: RU was 2165 -> 2155 over the last
30 days, while EN was 623 -> 653. Better meme selection alone is still not
enough to grow RU.

Operational finding: normal scheduled posts were not the only channel volume.
Weekly uploaded-meme reward albums add 5 media posts at once and were logged as
`score_version=1`, which mixed non-ranker posts into old-ranker readouts. The
May 21 cleanup sets reward album logs to `score_version=0` and keeps their
caption on the first media item for analysis.

Frequency adjustment: RU scheduled posts move from `8,10,11,12,14,16` MSK to
`8,10,14,16,21` MSK. This removes the 10/11/12 hourly cluster and moves one
slot into the evening reactivation window. Bot activity in the last 30 days:
21:00 MSK had 30.5k reactions / 367 active users; 22:00 MSK had 32.0k reactions
/ 349 active users. Use 21:00 first because the active-user base is slightly
wider and the slot is less late.

ML status: `scripts/eval_crossposting_ml.py` now runs a read-only logistic
baseline against 24h channel labels. Initial 90-day run:

| Channel | Labeled images | Logistic AUC | Source-signal AUC | Pre-share top20 lift |
| --- | ---: | ---: | ---: | ---: |
| RU | 164 | 0.491 | 0.568 | 1.96x |
| EN | 162 | 0.548 | 0.410 | 2.45x |

Conclusion: this is not yet strong enough to ship an ML ranker. The next useful
step is richer candidate-level offline evaluation, not turning on `score_version=3`.
Keep ML work timestamp-safe: labels from 24h snapshots, features only from data
available before the simulated decision.

May 22 correction: the first `pre_share_users_top20_lift` readout was inflated
by evaluator tie-bias. `top_quintile_lift` sorted `(score, label)` tuples, so
equal scores placed positive labels before negative labels. After making ties
label-neutral, `pre_share_users` is not shippable: the 120-day split has only
1/52 RU test posts and 0/51 EN test posts with positive pre-share coverage;
the corrected pre-share top20 lift is 0.93x for RU and 1.00x for EN. Keep prior
share clicks as a logged feature until coverage improves.

### Segment-first ML plan

The flat meme-level model is not the right abstraction. The next evaluator
should model `meme x user_segment` evidence first, then aggregate segment
responses into a channel-success prediction.

User segments to test before any production ranker:

- Engagement depth: new, casual, regular, heavy, based on recent reaction count
  and active days.
- Taste/source affinity: top source clusters per user from historical likes and
  skips; start with `meme_source_id` families, add OCR/description embeddings
  only after the tabular baseline is sane.
- Reaction behavior: fast liker, slow reader, fast skipper, high-share clicker.
- Language/context: selected languages, observed liked meme language, local
  active-hour bucket.

Candidate segment features:

- Segment impressions before channel post.
- Segment like rate and Wilson-smoothed like rate.
- Segment median reaction time and fast-skip rate.
- Segment in-bot share click users.
- Coverage: number of distinct segments with enough evidence.

Targets should stay channel-specific:

- Primary target: `forwards_24h / views_24h` above channel rolling median or
  top quartile. This captures shareability without over-rewarding high reach.
- Secondary target: reaction rate above rolling median.
- Reach target: `views_24h` above expected views for that channel/hour/day.
  Keep reach separate because post timing and subscriber base can dominate it.

Do not train on all-time aggregates such as current `meme_stats.invited_count`
for historical examples. Every feature must be reconstructed as of the simulated
decision time.
