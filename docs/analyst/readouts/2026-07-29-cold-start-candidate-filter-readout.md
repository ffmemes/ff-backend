# Cold-Start Candidate Filter Post-Gate Readout

Date: 2026-07-29
Historical issue: FFM-1939
Decision: complete as a directional success; retain the guarded behavior

## Result

The checkpoint included 37 guarded users, clearing the predeclared directional
sample gate.

| Cohort | Reached ten sends |
|---|---:|
| Guarded treatment | 32.4% |
| Pre-experiment baseline | 26.8% |
| Concurrent control | 11.1% |

The treatment improved against both comparisons, although it did not reach the
stretch target of 35%. First-meme continuation and first-10 like-rate
guardrails passed. No treatment leakage into unrelated routing was observed.

## Treatment Definition

Guarded treatment means the user's first 10 sends included at least one
`cold_start_explore_guarded` or `cold_start_adapt_guarded` recommendation.
Unguarded control means first-10 cold-start exposure without a guarded label.

The exact guarded source slice from PR #331 was:

- `https://vk.com/dfzwe4`
- `https://vk.com/eternalclassic`
- `https://t.me/ukrmemesmineproblemes`
- `https://t.me/hindi_jokes_desi_memes`

The implementation filtered those source URLs only from guarded cold-start
candidate engines. It intentionally preserved non-guarded first-position
traffic and fallback labels so cold-start delivery would not starve if guarded
pools were empty.

## Gate Metrics

| Metric | Baseline | Guarded treatment | Unguarded control | Read |
|---|---:|---:|---:|---|
| Sample users | 56 | 37 | 9 | Treatment gate met; control remains tiny |
| Reached 5 | 58.9% | 26/37 = 70.3% | 4/9 = 44.4% | Pass |
| Reached 10 | 26.8% | 12/37 = 32.4% | 1/9 = 11.1% | Directional pass; below 35% absolute target |
| First-10 continuation | 69.8% | 73.3% | 55.3% | Pass |
| Positions 2-5 continuation | baseline weak slice | 69.9% | 63.2% | +6.7pp vs control; pass |
| First-meme continuation | 87.5%; floor 84% | 100.0% | 44.4% | Pass |
| First-meme reaction rate | Not measured | 67.6% | 33.3% | Treatment stronger |
| First-meme LR among reactions | 41.4% | 44.0% | 66.7% | Control n=3 reacted; not decision-bearing |
| First-10 LR | 39.5%; floor 36.5% | 46.8% | 44.4% | Pass |
| Second-session users | 55.4% | Not measured | Not measured | Explicitly unmeasured after launch; do not infer |

July 28 checkpoint cross-check: the prior heartbeat had 32 guarded users,
reached-10 31.3%, first-10 continuation 69.8% vs 48.9% unguarded, and
positions 2-5 continuation 70.2% vs 61.9%. The July 29 recompute preserved the
positive direction after additional users.

## Candidate Pool And Mix

Fallback label proxy: non-cold-start first-10 sends were 24.3% in treatment vs
23.7% in control, so there was no fallback spike. The requested diagnostics
field `fallback_used` was emitted to logs/Sentry only; no durable
recommendation diagnostics table was present in the database.

Engine mix in treatment:

| Engine label | Treatment sends | Share |
|---|---:|---:|
| `cold_start_explore_guarded` | 152/243 | 62.6% |
| `cold_start_explore` first-position traffic | 31/243 | 12.8% |
| `lr_smoothed` fallback | 40/243 | 16.5% |
| `share_link` | 10/243 | 4.1% |
| `cold_start_adapt_guarded` | 1/243 | 0.4% |

The low adapt volume means this readout mainly validates guarded Phase 1 /
positions 2-5, not Phase 2 personalization.

Language mix in treatment: RU 60.9% of sends with 49.0% LR and 77.7%
continuation; EN 27.2% with 32.1% LR and 59.1% continuation; UK 7.4% with
50.0% LR and 88.9% continuation. This does not require a language reweight:
the v1 plan measured language as a guardrail, and the winning signal is source
exclusion plus continuation, not language forcing.

Top treatment sources by first-10 sends:

| Source | Sends | LR | Continuation |
|---|---:|---:|---:|
| `https://vk.com/mysterious_conditions` | 61 | 52.5% | 70.5% |
| `https://t.me/twitt_ota` | 18 | 50.0% | 88.9% |
| `https://vk.com/wtf.rasha` | 17 | 45.5% | 100.0% |
| `https://t.me/pan_gik` | 11 | 50.0% | 100.0% |
| `https://t.me/admeme` | 10 | 0.0% | 40.0% |

`admeme` is worth watching in future cold-start scoring, but not enough to
block this gate.

## Guarded Source Leakage

Leakage on guarded engines was 0/153 sends. There were 20 sends from the
guarded source list in first-10 treatment/control rows, but they came through
non-guarded first-position or fallback labels (`cold_start_explore`,
`lr_smoothed`, `share_link`), which the experiment intentionally preserved. No
guarded-source leak was visible in `cold_start_explore_guarded` or
`cold_start_adapt_guarded`.

## Product Health Guardrails

Product health was green for this gate: North Star median was 21 vs 20 prior
7d, DAU 175, WAU 384, 21,147 reactions in 24h, 524 new memes in 24h, and
ok_pct 95.0%.

Stats freshness passed: `user_stats` refreshed at 2026-07-29T19:30:00Z and
`meme_stats` refreshed at 2026-07-29T19:33:00Z. No candidate-pool delivery
issue was visible: first-10 fallback share was flat versus control and guarded
engines served 153 first-10 guarded sends without guarded-source leakage.

## Decision

Complete the experiment as a directional success and keep the guarded behavior.
Do not broaden the source exclusions or change mature-user routing from this
sample. Future work should be justified by a new position-level hypothesis,
not by reopening this completed measurement loop.

## Reusable Lesson

A modest sample can support a bounded decision when the directional sample gate,
baseline, control, and regression guardrails are declared before the readout.
