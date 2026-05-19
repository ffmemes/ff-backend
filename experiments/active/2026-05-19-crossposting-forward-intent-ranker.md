# Experiment: Crossposting Forward-Intent Ranker
Created: 2026-05-19
Status: proposed - offline evaluator, then RU-only canary
Owner: analyst + engineer
Deployed: pending
Measure after: pending

## Hypothesis

Source-level share history is useful, but not enough to select the actual meme
that will be forwarded. Telegram channel forwards should be predicted by a
content-level "forward intent" score observed before channel posting:

1. Timestamp-safe in-bot share clicks for the exact meme.
2. Users whose historical share clicks, not likes, preceded channel-forward
   wins.
3. Source-level channel-forward prior as a fallback, not the dominant term.

Primary target: `forwards_per_1k_views` at 24h after channel posting.
Secondary target: absolute `forwards_24h`.

## Current Evidence

On 2026-05-19 we manually posted two `score_version=3` share-max candidates that
were chosen mostly from source-level channel-forward history:

| Channel | Meme | Age at check | Views | Forwards | Fwd/1k | Read |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| RU | 4643497 | 3.2h | 218 | 6 | 27.5 | good, not exceptional |
| EN | 994936 | 3.2h | 37 | 0 | 0.0 | failed |

RU was around the 74th percentile against mature 30-day `score_version=2`
posts by fwd/1k, but only around the 44th percentile against early 1-8h
snapshots. EN was below the median on both forwards and fwd/1k.

Interpretation: source prior alone can find acceptable RU memes, but it did not
produce a breakout and should not be promoted to the scheduled ranker. EN should
remain separate; current EN share signals are not positive.

## Next Plan

### Phase A: Offline Evaluator

Build a read-only evaluator that reconstructs candidate signals as of each
historical channel decision:

1. Label outcomes from the nearest 3h, 6h, and 24h channel snapshots.
2. Use only `user_deep_link_log` share clicks created before the channel
   decision.
3. Exclude self-clicks encoded as `s_{sharer_user_id}_{meme_id}`.
4. Train share-user weights from historical share-click lift, not from likes.
5. Split per channel by time: train, validation, test.
6. Compare four variants:
   - current `score_version=2`;
   - source-prior-only share-max;
   - exact-meme prior-share-only;
   - hybrid forward-intent score.

Offline success gate:

- RU test coverage >= 10% of candidate posts with an exact-meme prior-share
  signal, or the feature is too sparse for hot ranking.
- Hybrid Spearman correlation beats current v2 and source-prior-only by >= 0.05.
- Top-20% hybrid-ranked posts beat v2 top-20% by >= 20% on `forwards_24h`.
- Absolute `forwards_24h` does not drop when fwd/1k improves.
- EN must pass the same gate independently before any EN online posting.

### Phase B: RU-Only Canary

If Phase A passes for RU, post 5 RU canary slots over 24-48 hours using the
hybrid score. Keep these as manual or one-shot `score_version=3` posts; do not
replace the scheduled ranker yet.

Canary pass criteria:

- Mean early fwd/1k is above the RU v2 early p75 baseline observed on
  2026-05-19: about 39 forwards per 1k views.
- Mean early absolute forwards is above the RU v2 early p75 baseline: about
  9 forwards.
- Views are not more than 20% below the comparable early v2 median.
- No source supplies more than 2 of the 5 canary posts.

Stop the canary early if two consecutive posts land below the early v2 median
on both absolute forwards and fwd/1k.

### Phase C: Online A/B

Only after the RU canary passes:

- Add a small scheduled RU exploration bucket: 10-20% of channel slots.
- Keep v2 as control.
- Keep one source per 24h diversity cap.
- Keep image-only policy.
- Keep EN disabled until it has its own positive offline result.

Candidate score:

```text
forward_intent_score =
  source_forward_prior
  * (1 + capped_exact_meme_prior_share_users)
  * (1 + capped_weighted_share_user_lift)
  * quality_guardrails
```

Initial caps should be conservative:

- exact-meme prior-share users: max +50%;
- weighted share-user lift: max +30%;
- source prior: keep as a rank floor, not an unlimited multiplier.

## Metrics

Primary:

- `forwards_per_1k_views_24h`
- `forwards_24h`

Early read:

- `forwards_per_1k_views_3h`
- `forwards_3h`
- views at 3h to catch reach loss

Guardrails:

- No skipped posting slots due to empty pool.
- No post-after-post leakage in offline evaluation.
- EN and RU model weights are trained and evaluated independently.
- Human review link is available for one-shot candidates before posting.

## Implementation Notes

- Reuse the existing `score_version=3` decision-log fields:
  `share_source_base`, `share_user_boost`, `share_invited_boost`,
  `share_max_base_score`, and `share_max_score`.
- Add a candidate preview/report step before manual posting so the selected
  source URL can be reviewed.
- Do not compute predictor-user weights inline in the hot crossposting SQL.
  Materialize or cache them if the offline evaluator passes.
- Keep the current scheduled crossposting ranker at `score_version=2` until the
  RU canary passes.

## Metrics After

Pending.

## Conclusion

Pending. Current read: the next useful bet is not "more source prior"; it is a
timestamp-safe forward-intent feature based on exact-meme share behavior and
historically good share users, tested RU-first.
