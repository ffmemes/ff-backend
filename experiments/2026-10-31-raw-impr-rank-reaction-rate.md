---
id: raw_impr_rank_reaction_rate
status: inconclusive
hypothesis: Within-source reaction rate (reactions/views) beats views for ranking cold memes
primary_metric: like rate of memes with raw_impr_rank = 0, 3 weeks before vs after deploy
guardrails: LR of engines that use the rank (candidates.py rank-0 pool, crosspost impr penalty)
unit: meme
variants: none (pre/post)
started: 2026-10-31
check_on:
decided: 2026-11-15
result: no valid pre/post estimate; feed impressions do not retain rank/version at selection or send, and meme_stats rank is overwritten
learning: A current-rank join cannot measure historical rank-0 cohorts; retain the deployed algorithm without claiming uplift and measure future changes prospectively
code: meme_raw_telegram.reactions, calculate_meme_raw_impressions_stats (PR #384)
readout: 
---

# Experiment: raw_impr_rank by reaction rate

Shipped 2026-10-31 in PR #384. `raw_impr_rank` is now the quartile of
`reactions / views` within source x meme type (VK rows and rows without reactions
rank by views after rated rows). Also fixed an off-by-one: the top meme of a small
source never got rank 0. Existing rows keep `reactions = NULL` until re-parsed, so the
switch is gradual.

## Evidence (2026-10-31, 3,622 memes / 97 sources)

- Views quartile vs our like rate: Spearman +0.02.
- Within-source reaction-rate percentile: Spearman +0.22 [0.18, 0.27]; top vs bottom
  quintile like rate 0.44 vs 0.35; holds on cold memes' first 30 reactions.

## Decision rule

Kill (revert to views) if the like rate of rank-0 memes does not rise over 3 weeks
after deploy vs 3 weeks before. No readout SQL committed yet.


## Readout 2026-11-15

Checkpoint: live rank is overwritten in place and no frozen readout SQL exists. Current-rank joins cannot recover rank-at-send pre/post cohorts. Investigate historical reconstruction before Nov21; otherwise register prospective measurement. No valid outcome estimate yet. [Reconciled evidence](../docs/analyst/readouts/2026-11-22-experiment-check.md).

## Decision 2026-11-15 — close the retrospective as inconclusive

The source audit found no complete historical rank/version on feed impressions:
`src/database.py` and the write in `src/recommendations/service.py` store the meme,
engine and timestamps, while `src/stats/meme.py` overwrites the current rank.
`like_spread_and_recent` marks only a subset of rank-0 selections; other engines
also serve ranked memes. Crosspost decision logs cover channel candidates, not
the full feed. External backups/archives were not audited.

Close this measurement design and cancel the Nov21 reconstruction obligation.
This is no evidence of benefit or harm, so do not apply the old rollback rule to
an invalid current-rank comparison. The deployed reaction-rate ranking remains.
A sufficient historical archive could reopen measurement; otherwise a new
experiment needs a prospective version/rank snapshot or randomized ranking
assignment and committed readout SQL before launch.
