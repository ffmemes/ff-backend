# Channel-hit ranking: measured outliers and a simple rule

Read-only production analysis, 5 September 2026. The same fixed UTC cutoff,
20–36-hour nearest-24h snapshots, current deliverable published images, and
reward-post exclusion as `inventory.sql` are used. Full period: posts since
May 8 and before September 3 12:00. Recent period: posts since August 6.
Only aggregate results are retained.

## Decision

Keep the upper-quarter pool for supply, and show its strongest candidates
first. Do not require a statistical outlier: there are only **three per
channel** in the full period and **one RU / zero EN** among recent posts.
Sorting the pool is important; a p75 eligibility floor is not a proposal to
sample every qualifying meme with equal probability.

| Eligible rule | RU full / recent | EN full / recent |
| --- | ---: | ---: |
| Forward rate at or above channel p75 | 155 / 47 | 154 / 33 |
| Forward rate at or above channel p90 | 62 / 18 | 60 / 13 |
| Statistical high outlier: above Q3 + 1.5 × IQR | 3 / 1 | 3 / 0 |
| Smoothed-rate p75 with at least 50 views | 155 / 47 | 155 / 33 |

These are global pools before user-specific language, subscription and
previous-delivery exclusions. Earlier per-user coverage belongs to the raw
p75 rule, not the p90 or outlier alternatives.

## Scale and uncertainty

| Mature 24h statistic | RU | EN |
| --- | ---: | ---: |
| Posts | 620 | 600 |
| Median views | 353 | 74 |
| Minimum views | 282 | 59 |
| Median forwards | 9 | 1 |
| p90 forwards | 14 | 3 |
| Maximum forwards | 64 | 6 |
| Median forwards per 1,000 views | 24.53 | 13.70 |
| p75 forwards per 1,000 views | 32.28 | 26.67 |
| p90 forwards per 1,000 views | 39.01 | 39.01 |
| Outlier cutoff, forwards per 1,000 views | 54.51 | 66.67 |

EN has 581 of 600 posts below 100 views. A shared 100-view minimum would
discard almost the entire EN sample. A three-forward minimum would shrink
the EN p75 pool from 154 to 93 and recent inventory from 33 to 21. The RU
p75 pool already has at least ten forwards per post. Thus a universal large
count cutoff creates different products for the two languages.

No observed post has fewer than 50 views. A 50-view floor therefore preserves
the present pool and guards against future tiny denominators. EN remains
noisy: two or three forwards are evidence of relatively strong channel
performance, not proof of a repeatable viral property. Channel forwards are
not necessarily independent viewer-level Bernoulli events.

## Proposed calculation

For each channel, use only mature reference posts in the same rolling window:

```text
mu = sum(forwards_24h) / sum(views_24h)
k = median(views_24h)
smoothed_rate = (forwards_24h + k * mu) / (views_24h + k)
```

Today `k` is **353 RU / 74 EN**, and `mu` is **0.025444858 RU /
0.016814450 EN**. This gives one typical post's exposure to the channel prior.
It is a simple conservative regularizer, not an estimated optimum or a
formal confidence interval. For a typical-sized post it halves the deviation
from the channel baseline; for an unusually large post it trusts more of the
observed rate. Recompute per channel, rather than hardcoding today's values.

Keep raw-rate p75 plus the 50-view floor for eligibility, to preserve the
already audited pool. Rank eligible posts by smoothed rate within their
channel. If candidates from multiple languages compete in one list, use the
within-channel percentile of the smoothed rate for comparable hit strength,
while preserving explicit language preferences. Break comparable-score ties
by recency. Subscription and prior-delivery/dedup exclusions still apply.

The smoothing changes upper-quarter membership very little in this data:
154 of 155 RU and all 154 original EN winners remain in the smoothed p75
pool. It protects future edge cases without turning this pilot into a new
modeling project. Top-decile posts naturally appear first when ranking; the
rest of the upper quarter supplies the next candidates when those are seen
or excluded. Do not claim growth until the retained-referral experiment is
observed.

## Reproduction

- `distribution.sql` / `.json`: quantiles, counts and denominator floors.
- `distribution-rules.sql` / `.json`: p75, p90, IQR-outlier and shrinkage supply.

Run reviewed SQL with the parent `run_readonly.py`: transactions are read-only
with a 30-second statement timeout. No private identifiers, content, credentials
or connection settings are exported.
