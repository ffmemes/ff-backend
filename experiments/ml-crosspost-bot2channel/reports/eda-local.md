# Local EDA — bot→channel

**Built:** 2026-08-11T18:01:38.756678+00:00
**n:** 3889
**posted_at:** 2023-11-30 06:37:46 → 2026-08-11 13:20:01

## Correlations (Spearman)

| feature | vs f1k | vs forwards | vs resid_f1k |
|---------|-------:|------------:|-------------:|
| `pre_ln_likes` | 0.062 | 0.063 | 0.061 |
| `pre_lr` | 0.001 | 0.082 | 0.039 |
| `pre_likes` | 0.062 | 0.063 | 0.061 |
| `pre_reacts` | 0.062 | 0.049 | 0.058 |
| `pre_engaged_likes` | 0.066 | 0.072 | 0.065 |
| `pre_premium_like_frac` | 0.022 | -0.176 | 0.040 |
| `src_prior_f1k` | 0.191 | 0.173 | -0.235 |
| `src_prior_n` | -0.059 | -0.202 | 0.017 |
| `log1p_hours_in_bot` | 0.046 | -0.097 | 0.010 |
| `v4_proxy` | 0.062 | 0.063 | 0.061 |

## Saturation bands (pre_likes)

| band | n | avg_likes | avg_f1k | avg_fwd |
|------|--:|----------:|--------:|--------:|
| 1 | 834 | 5.6 | 17.35 | 17.74 |
| 2 | 746 | 15.2 | 18.62 | 16.52 |
| 3 | 755 | 33.4 | 18.48 | 17.70 |
| 4 | 782 | 74.9 | 18.76 | 18.99 |
| 5 | 772 | 180.3 | 18.67 | 17.81 |

## Missingness

- `pre_ln_likes`: 0.0% null
- `pre_lr`: 0.0% null
- `pre_likes`: 0.0% null
- `pre_reacts`: 0.0% null
- `pre_engaged_likes`: 0.0% null
- `pre_premium_like_frac`: 3.9% null
- `src_prior_f1k`: 7.9% null
- `src_prior_n`: 7.9% null
- `log1p_hours_in_bot`: 0.0% null
- `v4_proxy`: 0.0% null
- `src_prior_f1k`: 7.9% null
- `pre_premium_like_frac`: 3.9% null
