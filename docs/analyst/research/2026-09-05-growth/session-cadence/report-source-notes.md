# FFMemes session cadence: report source notes

Source: AI analysis. Audience: product stakeholders / founder. Delivery: portable HTML; no publishing.

## Reporting job

- Question: Does a calendar day describe FFMemes visits poorly, and is there a recurring within-day session pattern?
- Decision: Whether to replace the first-calendar-session opportunity with an inactivity-based session opportunity while preserving an explicit experiment exposure cap.
- Scope: Clean voluntary meme sends during 12 August–4 September 2026 inclusive; frozen 85-user experiment cohort compared with all users.
- Sensitivity: Session boundaries at 15, 30, and 60 minutes without clean voluntary sends.
- Success criterion: Show the repeated-visit pattern, its stability across boundary choices, and the resulting policy implication without claiming a causal effect on growth.

## Report structure contract

The `product stakeholders` executive specification was read before drafting.

1. Matching title block.
2. Visible `Executive Summary` section (Russian summary; English label retained by the contract).
3. Findings and metric definitions, with a compact native grouped bar chart. The chart compares repeat-session incidence across the three inactivity thresholds and two populations. A compact table may retain exact denominators and related measures when they improve auditability.
4. Recommendation and open questions combined: define session boundaries and exposure cap separately; distinguish observed cadence from untested growth or ideal frequency claims.
5. Caveats near their relevant finding and a compact closing caveat paragraph.

The required `Recommended next steps` and `Further questions` roles are combined because one decision is under review. Reproducibility and source inventories remain in source metadata and this file, not a reader-facing appendix.

## Chart contract

- Question: Does the repeat-session finding depend on calling a pause 15, 30, or 60 minutes?
- Family: comparison; grouped bar; six population/threshold aggregates. This is sensitivity analysis, not a three-point time trend.
- X: inactivity threshold in natural order 15, 30, 60 minutes.
- Y: share of active user-days with multiple observed sessions. The final artifact will carry exact numerator and denominator where supplied.
- Group: frozen experiment cohort versus all qualifying users.
- Palette: two restrained roots from the canonical shared chart renderer; labeled legend and ordered x-axis provide non-color distinctions.
- Surface: canonical `artifact.json` native chart, packaged by `report:deliver` into one self-contained `report.html`.
- No custom chart renderer, remote assets, individual user identifiers, or credentials.

## Reviewed source inventory and transformations

- `data.json`: root analyst's reviewed aggregate result, extracted at 19:22–19:23 UTC on 5 September 2026. This is the narrative source of record.
- `summary.sql`: session summaries from `public.user_meme_reaction`, `public.user`, and `public.experiment_assignment`. The report preserves the executed logic, replacing the two bind parameters with the actual study bounds in source metadata.
- `replay.sql` and `replay.py`: original session-level source query and downstream rolling-cap simulation. The report contains aggregate outcomes only; no per-user records are included.
- Main result: 904 / 1,342 = 67.36% repeat-session days in the pilot at 30 minutes; 1,501 / 2,705 = 55.49% for all users. The all-users segment includes the pilot.
- The sensitivity chart retains all six reviewed population/threshold aggregates, including exact repeat-day numerators, active-day denominators, user counts, session counts, and median sessions per day.
- The policy table uses exactly 1,342, 1,929, 2,539, and 4,075 opportunities. Ratios are calculated against 1,342. Calendar-day cap-two/cap-three counts are intentionally excluded from the displayed comparison because the proposed policy uses rolling 24-hour limits.
- Reaction sensitivity: 822 / 1,282 = 64.12% repeat-session days at 30 minutes.
- Displayed pause: 1.29906724 hours × 60 = 77.944 minutes, rounded to 78. Session duration is the elapsed interval between retained sends, not measured viewing time.
- Opportunity replay ignores inventory depletion, behavior changes, and exposure history before the study window. It is not an estimate of actual experimental deliveries, treatment effect, or growth.
- Cadence policy statements describe the root agent's new-version specification. The report uses durable neutral wording: one hit at the start of each session, at most three per rolling 24 hours; the effect on growth is not yet measured. It makes no claim about deployment status; production deployment is outside this subtask.

## Build and verification

Canonical files: `artifact.json` and generated `report.html`. The portable builder packages the shared reader, semantic fallback, native chart, table, and source interactions; no bespoke rendering implementation was used.

The first packaging attempt required actual SQL in the table's source metadata despite retaining the reproducible Python source path. The narrow correction added the original `replay.sql` query and explained that the subsequent rolling-cap calculation lives in `replay.py`; the report's content and data were preserved.

Final `report:deliver` receipt: validation passed; package passed; verification passed. The packaged verifier checked 8 blocks, 1 native chart, 1 native table, source-dialog interaction, desktop width 1,440 and narrow width 390, exact embedded artifact equality, and absence of browser/network errors. This is the skill's sufficient per-report QA receipt; no redundant bespoke browser scripts or screenshots were produced.

No production calls, code changes, public publication, or individual-user data exports were performed by the report task.

A narrow pre-release wording revision changed only the title subline and the policy section's final status sentence. Historical evidence, quantitative values, datasets, sources, block order, and the recommendation were preserved. The original canonical artifact was repackaged after this correction.
