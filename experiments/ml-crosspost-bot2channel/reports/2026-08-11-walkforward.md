# Walk-forward validation — 2026-08-11

- n_total=3659
- features=['pre_ln_likes', 'pre_lr', 'pre_reacts', 'pre_engaged_likes', 'pre_premium_like_frac', 'pre_premium_likes', 'src_prior_f1k', 'src_prior_n_log', 'has_caption_i', 'log1p_hours_in_bot']
- pass bar: lift ≥ v4+0.05 on ≥2/3 folds; mean spearman gap < 0.25

## Folds

| fold | n_train | n_test | train_end | test window | hit_p75 | hit_rate_te |
|-----:|--------:|-------:|-----------|-------------|--------:|------------:|
| 1 | 1829 | 548 | `2025-06-12 05:20:01` | `2025-06-12 07:20:00` → `2025-11-03 09:20:00` | 23.21 | 0.217 |
| 2 | 2378 | 548 | `2025-11-03 11:20:07` | `2025-11-04 05:20:00` → `2026-03-24 13:20:00` | 22.96 | 0.221 |
| 3 | 2927 | 548 | `2026-03-24 15:20:00` | `2026-03-25 05:20:00` → `2026-07-09 07:20:02` | 22.76 | 0.285 |

## Per-fold metrics

| fold | model | lift_f1k | lift_fwd | spearman_te | spearman_gap | AUC | AP |
|-----:|-------|---------:|---------:|------------:|-------------:|----:|---:|
| 1 | hgb_clf_depth3 | 1.015 | 1.022 | 0.060 | 0.341 | 0.548 | 0.241 |
| 1 | hgb_reg_depth3 | 1.049 | 1.051 | 0.134 | 0.313 | 0.598 | 0.272 |
| 1 | logreg_hit | 1.005 | 0.961 | 0.065 | 0.178 | 0.535 | 0.247 |
| 1 | ridge_f1k | 1.038 | 0.997 | 0.092 | 0.170 | 0.562 | 0.264 |
| 1 | src_prior_f1k | 1.025 | 1.038 | 0.027 | 0.179 | 0.520 | 0.241 |
| 1 | v4_proxy | 1.043 | 1.050 | 0.056 | -0.038 | 0.539 | 0.238 |
| 2 | hgb_clf_depth3 | 1.076 | 1.050 | 0.109 | 0.261 | 0.567 | 0.280 |
| 2 | hgb_reg_depth3 | 1.083 | 1.087 | 0.075 | 0.332 | 0.542 | 0.274 |
| 2 | logreg_hit | 1.109 | 1.190 | 0.103 | 0.108 | 0.580 | 0.276 |
| 2 | ridge_f1k | 1.093 | 1.125 | 0.097 | 0.130 | 0.562 | 0.268 |
| 2 | src_prior_f1k | 1.000 | 0.982 | 0.051 | 0.117 | 0.544 | 0.263 |
| 2 | v4_proxy | 1.016 | 1.046 | 0.027 | -0.003 | 0.497 | 0.233 |
| 3 | hgb_clf_depth3 | 1.087 | 1.095 | 0.043 | 0.319 | 0.532 | 0.356 |
| 3 | hgb_reg_depth3 | 1.094 | 1.079 | 0.119 | 0.271 | 0.566 | 0.379 |
| 3 | logreg_hit | 0.951 | 0.978 | 0.023 | 0.178 | 0.511 | 0.291 |
| 3 | ridge_f1k | 0.998 | 1.019 | 0.072 | 0.139 | 0.541 | 0.307 |
| 3 | src_prior_f1k | 1.171 | 1.157 | 0.190 | -0.038 | 0.594 | 0.359 |
| 3 | v4_proxy | 1.085 | 1.054 | 0.106 | -0.073 | 0.561 | 0.364 |

## Aggregate vs pass bar

| model | wins vs v4 | mean lift f1k | mean v4 lift | mean spearman gap | gap_ok | PASS |
|-------|-----------:|--------------:|-------------:|------------------:|:------:|:----:|
| hgb_clf_depth3 | 1/3 | 1.059 | 1.048 | 0.307 | False | no |
| hgb_reg_depth3 | 1/3 | 1.075 | 1.048 | 0.305 | False | no |
| logreg_hit | 1/3 | 1.022 | 1.048 | 0.154 | True | no |
| ridge_f1k | 1/3 | 1.043 | 1.048 | 0.146 | True | no |
| v4_proxy | — | 1.048 | — | -0.038 | — | baseline |

## Verdict

**HOLD / FAIL walk-forward** — no model clears lift vs v4 on ≥2 folds with overfit guard.
Closest: `hgb_reg_depth3` wins 1/3, mean lift 1.075 (v4 1.048), gap=0.305.
Keep production v4; do not ship linear/logreg/HGB.

Single 70/30 split can look better than walk-forward — trust this report more.
