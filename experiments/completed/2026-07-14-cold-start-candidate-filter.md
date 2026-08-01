# Experiment: Cold Start Candidate Filter

Created: 2026-07-14
Status: completed - directional success
Owner: ceo
Implementer: CTO
Implementation Issue: FFM-1882
Verification Issues: FFM-1883, FFM-1939
Deployed: 2026-07-16 in PR #331 (`f18ae381`)
Measured: 2026-07-29

## Hypothesis

True-new users were not primarily failing on the first meme. The July 13
first-10 readout showed first-meme continuation at 87.5%, but only 58.9% of
true-new users reached five sends and 26.8% reached ten. Excluding weak source
slices from cold-start positions 2–10 should improve depth without changing the
mature-user feed.

## Changes Made

- Scoped the treatment to true-new cold-start users.
- Added a feature-flagged candidate-source guardrail.
- Filtered this exact weak-source slice from guarded cold-start candidate
  engines:
  `https://vk.com/dfzwe4`, `https://vk.com/eternalclassic`,
  `https://t.me/ukrmemesmineproblemes`, and
  `https://t.me/hindi_jokes_desi_memes`.
- Preserved the existing fallback path to prevent candidate starvation.
- Persisted guarded recommendation attribution for measurement.
- Kept mature-user routing and `recently_liked_blender_v2` out of scope.

Implementation details from PR #331:

- Rollback: set `COLD_START_CANDIDATE_GUARDRAILS_ENABLED=false`.
- Guarded attribution labels:
  `cold_start_explore_guarded` and `cold_start_adapt_guarded`.
- Filter shape: guarded candidate SQL joins `meme_source` and excludes
  `S.url = ANY(:cold_start_guardrail_source_urls)`.
- Preserved routes: non-guarded first-position traffic and fallbacks
  (`cold_start_explore`, `lr_smoothed`, `share_link`,
  `text_light_lr_smoothed`, and `best_uploaded_memes` where applicable) were
  intentionally left available so empty guarded pools would not starve users.
- Not included in treatment: global language reweighting, a permanent
  individual-meme denylist, mature-user routing changes,
  `recently_liked_blender_v2`, moderator low-sent quota, or unrelated engines.

## Metrics Before

2026-07-13, fourteen-day true-new cohort (56 users):

- First-meme continuation: 87.5%.
- First-10 like rate: 39.5%; continuation: 69.8%.
- Reached five sends: 58.9%.
- Reached ten sends: 26.8%.
- Second-session users: 55.4%.
- Position-two continuation: 62.0%.

## Success Criteria

- Reached-10 improves from 26.8% to at least 35%, or is directionally positive
  with at least 30 treatment users.
- First-meme continuation does not fall below 84%.
- First-10 like rate does not fall by more than three percentage points.
- No candidate starvation or routing leakage.

## Metrics After

2026-07-29 checkpoint:

- Guarded treatment users: 37.
- Reached ten sends: 32.4% treatment versus 26.8% pre-experiment baseline and
  11.1% concurrent control.
- First-meme continuation and first-10 like-rate guardrails passed.
- No unrelated-routing leakage was observed.

Guardrail outcomes:

| Guardrail | Baseline/control | Guarded treatment | Outcome |
|---|---:|---:|---|
| 30-user decision gate | n/a | 37 users | Met |
| Reached five sends | 58.9% baseline; 44.4% control | 26/37 = 70.3% | Pass |
| Reached ten sends | 26.8% baseline; 11.1% control | 12/37 = 32.4% | Directional pass; below 35% stretch target |
| First-10 continuation | 69.8% baseline; 55.3% control | 73.3% | Pass |
| Positions 2-5 continuation | 63.2% control | 69.9% | Pass, +6.7pp vs control |
| First-meme continuation | 87.5% baseline; 84% floor | 100.0% | Pass |
| First-10 like rate | 39.5% baseline; 36.5% floor; 44.4% control | 46.8% | Pass |
| Fallback rate | 23.7% control non-cold-start first-10 label proxy | 24.3% | Pass; no fallback spike |
| Guarded-source leakage | Expected 0 on guarded engines | 0/153 guarded-engine sends | Pass |
| Source mix | Top source `https://vk.com/mysterious_conditions` 61 sends / 52.5% LR / 70.5% continuation; `https://t.me/admeme` watch item 10 sends / 0.0% LR / 40.0% continuation | Measured | No source-mix blocker |
| Language mix | RU 60.9%, EN 27.2%, UK 7.4% of treatment sends | Measured | Guardrail only; no language reweight |
| Product health | North Star 21 vs 20 prior 7d; DAU 175; WAU 384; 21,147 reactions/24h; ok_pct 95.0% | Green | Pass |
| Stats freshness | `user_stats` 2026-07-29T19:30:00Z; `meme_stats` 2026-07-29T19:33:00Z | Fresh | Pass |
| Second-session after value | Baseline 55.4% | Not present in final FFM-1939 artifact | Explicitly unmeasured; do not infer |

The final readout also recorded engine mix: `cold_start_explore_guarded`
152/243 treatment sends (62.6%), `cold_start_explore` first-position traffic
31/243 (12.8%), `lr_smoothed` fallback 40/243 (16.5%), `share_link` 10/243
(4.1%), and `cold_start_adapt_guarded` 1/243 (0.4%). This means the final
decision mainly validates guarded Phase 1 / positions 2-5, not Phase 2
personalization.

The guarded-source list appeared in 20 first-10 treatment/control rows through
non-guarded first-position or fallback labels (`cold_start_explore`,
`lr_smoothed`, `share_link`). That was intentional preservation of existing
routes, not leakage from `cold_start_explore_guarded` or
`cold_start_adapt_guarded`.

The early six-user spot check was intentionally non-decisive; see
[`2026-07-18-cold-start-candidate-filter-spotcheck.md`](../../docs/analyst/readouts/2026-07-18-cold-start-candidate-filter-spotcheck.md).
The final evidence is in
[`2026-07-29-cold-start-candidate-filter-readout.md`](../../docs/analyst/readouts/2026-07-29-cold-start-candidate-filter-readout.md).

## Conclusion

Directional success. The treatment cleared the declared 30-user alternative
gate and improved reached-10 versus both baseline and control without breaching
the first-meme, like-rate, fallback, or routing-scope guardrails.

Keep the guarded behavior. Do not broaden exclusions or change mature-user
routing without a new hypothesis and experiment.
