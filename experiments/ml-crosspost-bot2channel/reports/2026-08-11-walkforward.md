# Walk-forward validation — 2026-08-11

- n_total=624
- features=['pre_ln_likes', 'pre_lr', 'pre_reacts', 'pre_engaged_likes', 'pre_premium_like_frac', 'pre_premium_likes', 'src_prior_f1k', 'src_prior_n_log', 'has_caption_i', 'log1p_hours_in_bot']
- pass bar: lift ≥ v4+0.05 on ≥2/3 folds; mean spearman gap < 0.25

## Folds

| fold | n_train | n_test | train_end | test window | hit_p75 | hit_rate_te |
|-----:|--------:|-------:|-----------|-------------|--------:|------------:|
| 1 | 312 | 93 | `2026-06-14 07:20:01.234791` | `2026-06-14 11:20:01.704969` → `2026-07-01 07:20:02.021873` | 29.74 | 0.301 |
| 2 | 405 | 93 | `2026-07-01 07:20:02.021873` | `2026-07-01 11:20:02.080586` → `2026-07-17 18:20:02.133265` | 29.97 | 0.355 |
| 3 | 499 | 93 | `2026-07-18 05:20:07.662870` | `2026-07-18 07:20:01.847075` → `2026-08-04 11:20:02.373722` | 30.27 | 0.323 |

## Per-fold metrics

| fold | model | lift_f1k | lift_fwd | spearman_te | spearman_gap | AUC | AP |
|-----:|-------|---------:|---------:|------------:|-------------:|----:|---:|
| 1 | hgb_clf_depth3 | 1.015 | 1.035 | 0.035 | 0.521 | 0.532 | 0.344 |
| 1 | hgb_reg_depth3 | 1.039 | 1.041 | 0.015 | 0.670 | 0.503 | 0.351 |
| 1 | logreg_hit | 1.070 | 1.106 | 0.191 | 0.072 | 0.495 | 0.322 |
| 1 | ridge_f1k | 1.129 | 1.151 | 0.216 | 0.082 | 0.521 | 0.329 |
| 1 | src_prior_f1k | 0.995 | 1.009 | 0.141 | 0.046 | 0.512 | 0.300 |
| 1 | v4_proxy | 1.029 | 1.048 | -0.001 | 0.095 | 0.490 | 0.342 |
| 2 | hgb_clf_depth3 | 1.262 | 1.296 | 0.242 | 0.330 | 0.621 | 0.463 |
| 2 | hgb_reg_depth3 | 1.167 | 1.207 | 0.171 | 0.474 | 0.566 | 0.506 |
| 2 | logreg_hit | 1.203 | 1.207 | 0.218 | 0.036 | 0.602 | 0.522 |
| 2 | ridge_f1k | 1.205 | 1.207 | 0.151 | 0.147 | 0.554 | 0.484 |
| 2 | src_prior_f1k | 1.069 | 1.088 | 0.045 | 0.134 | 0.505 | 0.378 |
| 2 | v4_proxy | 1.020 | 0.999 | -0.032 | 0.120 | 0.493 | 0.451 |
| 3 | hgb_clf_depth3 | 0.943 | 0.952 | 0.053 | 0.512 | 0.476 | 0.307 |
| 3 | hgb_reg_depth3 | 1.222 | 1.263 | 0.178 | 0.471 | 0.540 | 0.393 |
| 3 | logreg_hit | 1.297 | 1.314 | 0.328 | -0.106 | 0.646 | 0.524 |
| 3 | ridge_f1k | 1.181 | 1.206 | 0.336 | -0.059 | 0.643 | 0.542 |
| 3 | src_prior_f1k | 0.905 | 0.914 | -0.132 | 0.304 | 0.416 | 0.274 |
| 3 | v4_proxy | 1.190 | 1.212 | 0.206 | -0.121 | 0.615 | 0.511 |

## Aggregate vs pass bar

| model | wins vs v4 | mean lift f1k | mean v4 lift | mean spearman gap | gap_ok | PASS |
|-------|-----------:|--------------:|-------------:|------------------:|:------:|:----:|
| hgb_clf_depth3 | 1/3 | 1.073 | 1.080 | 0.454 | False | no |
| hgb_reg_depth3 | 1/3 | 1.143 | 1.080 | 0.538 | False | no |
| logreg_hit | 2/3 | 1.190 | 1.080 | 0.001 | True | YES |
| ridge_f1k | 2/3 | 1.171 | 1.080 | 0.057 | True | YES |
| v4_proxy | — | 1.080 | — | 0.031 | — | baseline |

## Verdict

**PASS** — `logreg_hit` wins 2/3 folds (mean lift 1.190 vs v4 1.080).
Next: optional decision_log **shadow score only** (not sole ranker).

Single 70/30 split can look better than walk-forward — trust this report more.
