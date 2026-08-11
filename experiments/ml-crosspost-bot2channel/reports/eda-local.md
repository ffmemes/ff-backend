# Local EDA — bot→channel

**Built:** 2026-08-11T16:32:41.607846+00:00
**n:** 624
**posted_at:** 2026-04-11 09:20:00.647298 → 2026-08-09 18:20:07.079535

## Correlations (Spearman)

| feature | vs f1k | vs forwards | vs resid_f1k |
|---------|-------:|------------:|-------------:|
| `pre_ln_likes` | 0.100 | 0.059 | 0.174 |
| `pre_lr` | 0.042 | 0.083 | 0.012 |
| `pre_likes` | 0.100 | 0.059 | 0.174 |
| `pre_reacts` | 0.104 | 0.058 | 0.183 |
| `pre_engaged_likes` | 0.158 | 0.124 | 0.216 |
| `pre_premium_like_frac` | -0.001 | -0.012 | 0.034 |
| `src_prior_f1k` | 0.178 | 0.184 | -0.149 |
| `src_prior_n` | 0.146 | 0.071 | 0.075 |
| `log1p_hours_in_bot` | 0.081 | 0.099 | 0.063 |
| `v4_proxy` | 0.100 | 0.059 | 0.174 |

## Saturation bands (pre_likes)

| band | n | avg_likes | avg_f1k | avg_fwd |
|------|--:|----------:|--------:|--------:|
| 1 | 131 | 8.3 | 23.16 | 8.98 |
| 2 | 135 | 12.7 | 23.66 | 8.56 |
| 3 | 109 | 19.2 | 25.75 | 9.10 |
| 4 | 124 | 36.6 | 22.68 | 7.92 |
| 5 | 125 | 197.3 | 26.19 | 9.44 |

## Missingness

- `pre_ln_likes`: 0.0% null
- `pre_lr`: 0.0% null
- `pre_likes`: 0.0% null
- `pre_reacts`: 0.0% null
- `pre_engaged_likes`: 0.0% null
- `pre_premium_like_frac`: 0.0% null
- `src_prior_f1k`: 4.6% null
- `src_prior_n`: 4.6% null
- `log1p_hours_in_bot`: 0.0% null
- `v4_proxy`: 0.0% null
- `src_prior_f1k`: 4.6% null
- `pre_premium_like_frac`: 0.0% null
