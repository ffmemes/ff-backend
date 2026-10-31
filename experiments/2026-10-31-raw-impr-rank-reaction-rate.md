---
id: raw_impr_rank_reaction_rate
status: running
hypothesis: Within-source reaction rate (reactions/views) beats views for ranking cold memes
primary_metric: like rate of memes with raw_impr_rank = 0, 3 weeks before vs after deploy
guardrails: LR of engines that use the rank (candidates.py rank-0 pool, crosspost impr penalty)
unit: meme
variants: none (pre/post)
started: 2026-10-31
check_on: 2026-11-21
decided: 
result: unknown
learning: 
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
