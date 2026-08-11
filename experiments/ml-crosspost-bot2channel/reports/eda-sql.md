# SQL EDA — bot→channel

**When:** 2026-08-11T16:32:25.832680+00:00
**Channel:** tgchannelru, image, mature 18–36h

## 1) Label quantiles (180d mature)

| n | first_d | last_d | views_p50 | fwd_p50 | fwd_p75 | f1k_p25 | f1k_p50 | f1k_p75 | f1k_p90 | avg_react | avg_comments | hit_rate_fixed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 624 | 2026-04-11 | 2026-08-09 | 355.0 | 8.00 | 11.00 | 16.32 | 23.48 | 31.03 | 38.40 | 9.34 | 0.19 | 27.4 |

## 2) Coverage + premium

| n_labeled | pct_likes_ge5 | pct_likes_ge20 | pct_any_premium | avg_premium_frac | avg_pre_likes |
| --- | --- | --- | --- | --- | --- |
| 624 | 100.0 | 47.4 | 99.7 | 0.424 | 54.6 |

## 3) Quintiles pre_likes / pre_lr / premium_frac

### driver = pre_likes

| driver | q5 | n | avg_driver | avg_f1k | avg_fwd | avg_views | avg_react |
| --- | --- | --- | --- | --- | --- | --- | --- |
| pre_likes | 1 | 125 | 8.168 | 22.89 | 8.91 | 393.5 | 9.62 |
| pre_likes | 2 | 125 | 12.312 | 23.85 | 8.64 | 359.7 | 9.90 |
| pre_likes | 3 | 125 | 18.672 | 25.54 | 9.03 | 352.0 | 8.96 |
| pre_likes | 4 | 125 | 36.792 | 22.73 | 7.93 | 344.3 | 7.86 |
| pre_likes | 5 | 124 | 198.411 | 26.17 | 9.44 | 357.6 | 10.39 |

### driver = pre_lr

| driver | q5 | n | avg_driver | avg_f1k | avg_fwd | avg_views | avg_react |
| --- | --- | --- | --- | --- | --- | --- | --- |
| pre_lr | 1 | 125 | 0.442 | 23.31 | 8.10 | 344.4 | 7.78 |
| pre_lr | 2 | 125 | 0.481 | 24.21 | 8.61 | 353.6 | 9.35 |
| pre_lr | 3 | 125 | 0.507 | 24.43 | 9.28 | 383.4 | 9.41 |
| pre_lr | 4 | 125 | 0.544 | 24.43 | 8.74 | 355.8 | 9.73 |
| pre_lr | 5 | 124 | 0.608 | 24.78 | 9.23 | 370.0 | 10.46 |

### driver = premium_frac

| driver | q5 | n | avg_driver | avg_f1k | avg_fwd | avg_views | avg_react |
| --- | --- | --- | --- | --- | --- | --- | --- |
| premium_frac | 1 | 125 | 0.283 | 23.39 | 8.83 | 383.0 | 9.88 |
| premium_frac | 2 | 125 | 0.376 | 25.39 | 9.20 | 359.4 | 10.24 |
| premium_frac | 3 | 125 | 0.419 | 24.28 | 8.60 | 351.7 | 8.84 |
| premium_frac | 4 | 125 | 0.473 | 22.85 | 8.14 | 352.2 | 8.36 |
| premium_frac | 5 | 124 | 0.572 | 25.26 | 9.18 | 360.9 | 9.40 |

## 4) Source prior (90d lookback)

| n | n_prior_ge3 | r_prior_f1k | r_prior_fwd |
| --- | --- | --- | --- |
| 595 | 562 | 0.170 | 0.165 |
