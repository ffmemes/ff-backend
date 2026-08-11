# Walk-forward validation — 2026-08-11

- n_total=3877
- features=['pre_ln_likes', 'pre_lr', 'pre_reacts', 'pre_engaged_likes', 'pre_premium_like_frac', 'pre_premium_likes', 'src_prior_f1k', 'src_prior_n_log', 'has_caption_i', 'log1p_hours_in_bot']
- pass bar: lift ≥ v4+0.05 on ≥2/3 folds; mean spearman gap < 0.25

## Folds

| fold | n_train | n_test | train_end | test window | hit_p75 | hit_rate_te |
|-----:|--------:|-------:|-----------|-------------|--------:|------------:|
| 1 | 1938 | 581 | `2025-05-15 11:20:15.846082` | `2025-05-16 05:20:02.018341` → `2025-10-16 09:20:06.571530` | 23.18 | 0.704 |
| 2 | 2520 | 581 | `2025-10-16 11:20:01.297971` | `2025-10-17 05:20:00.823434` → `2026-03-15 11:20:00.911912` | 22.92 | 0.590 |
| 3 | 3101 | 581 | `2026-03-15 11:20:00.911912` | `2026-03-16 05:20:00.906349` → `2026-07-05 11:20:07.347929` | 22.77 | 0.430 |

## Per-fold metrics

| fold | model | lift_f1k | lift_fwd | spearman_te | spearman_gap | AUC | AP |
|-----:|-------|---------:|---------:|------------:|-------------:|----:|---:|
| 1 | hgb_clf_depth3 | 1.039 | 0.993 | 0.070 | 0.288 | 0.551 | 0.736 |
| 1 | hgb_reg_depth3 | 1.058 | 1.014 | 0.097 | 0.370 | 0.559 | 0.748 |
| 1 | logreg_hit | 1.072 | 1.025 | 0.063 | 0.196 | 0.562 | 0.768 |
| 1 | ridge_f1k | 1.065 | 1.013 | 0.091 | 0.186 | 0.569 | 0.776 |
| 1 | src_prior_f1k | 1.033 | 1.032 | 0.032 | 0.192 | 0.535 | 0.744 |
| 1 | v4_proxy | 1.030 | 1.026 | 0.022 | 0.042 | 0.541 | 0.725 |
| 2 | hgb_clf_depth3 | 1.019 | 0.990 | 0.081 | 0.269 | 0.523 | 0.610 |
| 2 | hgb_reg_depth3 | 1.081 | 1.106 | 0.114 | 0.285 | 0.549 | 0.622 |
| 2 | logreg_hit | 1.029 | 1.043 | 0.067 | 0.147 | 0.521 | 0.604 |
| 2 | ridge_f1k | 1.068 | 1.092 | 0.096 | 0.141 | 0.545 | 0.621 |
| 2 | src_prior_f1k | 0.992 | 0.978 | 0.045 | 0.139 | 0.512 | 0.594 |
| 2 | v4_proxy | 0.998 | 1.029 | 0.046 | -0.002 | 0.534 | 0.622 |
| 3 | hgb_clf_depth3 | 1.106 | 1.078 | 0.158 | 0.135 | 0.558 | 0.511 |
| 3 | hgb_reg_depth3 | 1.113 | 1.092 | 0.136 | 0.252 | 0.557 | 0.496 |
| 3 | logreg_hit | 1.079 | 1.068 | 0.133 | 0.054 | 0.566 | 0.498 |
| 3 | ridge_f1k | 1.028 | 1.024 | 0.093 | 0.124 | 0.552 | 0.462 |
| 3 | src_prior_f1k | 1.154 | 1.136 | 0.170 | -0.008 | 0.571 | 0.493 |
| 3 | v4_proxy | 1.065 | 1.052 | 0.085 | -0.039 | 0.527 | 0.504 |

## Aggregate vs pass bar

| model | wins vs v4 | mean lift f1k | mean v4 lift | mean spearman gap | gap_ok | PASS |
|-------|-----------:|--------------:|-------------:|------------------:|:------:|:----:|
| hgb_clf_depth3 | 0/3 | 1.055 | 1.031 | 0.231 | True | no |
| hgb_reg_depth3 | 1/3 | 1.084 | 1.031 | 0.302 | False | no |
| logreg_hit | 0/3 | 1.060 | 1.031 | 0.132 | True | no |
| ridge_f1k | 1/3 | 1.054 | 1.031 | 0.150 | True | no |
| v4_proxy | — | 1.031 | — | 0.000 | — | baseline |

## Verdict

**HOLD / FAIL walk-forward** — no model clears lift vs v4 on ≥2 folds with overfit guard.
Closest: `hgb_reg_depth3` wins 1/3, mean lift 1.084 (v4 1.031), gap=0.302.
Keep production v4; do not ship linear/logreg/HGB.

Single 70/30 split can look better than walk-forward — trust this report more.
