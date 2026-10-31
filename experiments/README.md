# Experiments

One file per experiment: `experiments/YYYY-MM-DD-slug.md` (date = when it was
designed or started). Status lives in the front matter, so files never move.
This README is generated: `python scripts/experiments.py index`.
**Read it before designing a new experiment:** the Decided table is everything
we tried and what we now believe.

Growth bar for new experiments: ship only if the funnel gets less leaky
(first tap / first like / reached-5) and/or the k-factor moves (unique non-self
share clicks, new-user invites). Session length and block rate are guardrails.
North star: [`SPEC.md`](../SPEC.md). Growth thesis:
[`docs/growth/virality-loop.md`](../docs/growth/virality-loop.md).

## Add, check, close

1. **Add:** copy the template into `experiments/YYYY-MM-DD-slug.md`, freeze the
   decision rule in the body, commit the readout SQL under `docs/analyst/`.
   Set `status: running` and `started:` when it deploys.
2. **Check:** `python scripts/experiments.py due` lists running experiments
   whose `check_on` has passed; `python scripts/experiments.py readout <id>`
   prints the command to run against `$ANALYST_DATABASE_URL` (read-only).
   Append dated numbers to the file's log.
3. **Close:** set `status` (shipped / killed / inconclusive), `decided`,
   `result` (numbers + CI or n) and `learning` (one line: what we now believe).
   Never delete the file. Readouts stay in `docs/analyst/readouts/`; link them.
4. Run `python scripts/experiments.py index` and commit the README with it.

Front matter is flat `key: value`; lists are comma-separated; unknown is `unknown`.
Status: proposed | running | shipped | killed | inconclusive.

```markdown
---
id: my_experiment_v1
status: proposed
hypothesis: one line, falsifiable
primary_metric: likes per active user per week
guardrails: LR not down >3 pp, block rate, empty queue
unit: user
variants: control:50,treatment:50
started:
check_on: YYYY-MM-DD
decided:
result: unknown
learning:
code: FLAG_NAME, src/path.py
readout: docs/analyst/my-experiment-v1.sql
---

# Experiment: my_experiment_v1

Design, assignment, frozen decision rules, confounds.

## Log
- YYYY-MM-DD: started (deploy sha / PR).
```

## Open (9)

| check_on | experiment | status | primary metric | hypothesis |
| --- | --- | --- | --- | --- |
| 2026-11-14 | [crosspost_v5_shadow](2026-10-30-crosspost-v5-shadow.md) | running | corr(score_v5, zf) - corr(v4, zf) >= 0.05 on posted picks, per channel | v5 score (source Beta hit rate x user taste, x like volume on RU) tracks channel virality better than v4 |
| 2026-11-14 | [onboarding_default_language_v1](2026-10-31-onboarding-default-language.md) | running | share of signups with >=1 meme sent, share with a first reaction | Defaulting unknown/bare-en users to en (instead of a blocking picker) gets every signup a first meme and more first reactions |
| 2026-11-20 | [broadcast_cadence_holdout_v1](2026-10-30-broadcast-cadence-holdout.md) | running | reactions/user/week (15m, 24h); active d7-14 (1w, 2w, 4w) | The 15m push mostly re-times sessions heavy users would start anyway; later steps (24h, 1w, 2w, 4w) bring back lapsing users |
| 2026-11-20 | [crosspost_content_tags_v5c](2026-10-31-crosspost-content-tags.md) | running | Gate A kappa >=0.6; Gate B refit coefficient <= -0.05 with CI excluding 0 | Relatable jokes and tweet screenshots get ~8-10% fewer RU forwards at equal source and likes; down-weighting them raises forwards per post |
| 2026-11-20 | [explore_budget_v1](2026-10-30-explore-budget.md) | running | likes per active user per week, memes per session | Spend exploration only on labeling fresh memes, show fresh winners to everyone, and fill the idle-return slot from like_spread |
| 2026-11-21 | [raw_impr_rank_reaction_rate](2026-10-31-raw-impr-rank-reaction-rate.md) | running | like rate of memes with raw_impr_rank = 0, 3 weeks before vs after deploy | Within-source reaction rate (reactions/views) beats views for ranking cold memes |
| 2026-11-28 | [crosspost_src_fwd_v5f](2026-11-01-crosspost-src-forward-rate.md) | running | RU Spearman gain rho_v5f - rho_v5 with 95% CI excluding 0 | Memes whose source post was forwarded more than usual for that source get more forwards in our channels |
| 2026-12-11 | [monthly_reminder_v1](2026-10-30-monthly-reminder.md) | proposed | react_30d_pct treated - holdout | One monthly HQ meme raises 30d activity of idle users who reacted before by >=3 pp at <2% blocks |
| - | [phash_shadow_v1](2026-10-31-phash-shadow-dedup.md) | running | precision on sampled exact-hash pairs, agreement with duplicate_of | An exact 64-bit dHash match finds duplicates OCR cannot (videos, animations, text-free images) with high precision |

## Decided (28, newest first)

| decided | experiment | status | result | learning |
| --- | --- | --- | --- | --- |
| 2026-10-31 | [ocr_dedup_watermark_fix](2026-10-31-ocr-dedup-watermark-fix.md) | shipped | false merges 43% to 2.5% at 93.5% recall (152 labelled merges, 60 days); 7,762 false-merged memes restored to ok | Watermark text made unrelated short captions look identical, and hub originals absorbed hundreds of dupes; strip boilerplate before text similarity |
| 2026-10-31 | [friend_challenge_h12](2026-10-30-friend-challenge.md) | killed | 0 participations ever | Nobody played, so the friend-invite idea is untested, not disproven |
| 2026-10-31 | [early_channel_popup](2026-04-20-early-channel-popup.md) | shipped | unknown (shipped as default without a readout) | none: unmeasured, do not cite as evidence |
| 2026-10-31 | [crossposting_forward_intent_ranker](2026-05-19-crossposting-forward-intent-ranker.md) | killed | unknown (never built); 2 manual source-prior posts: RU 27.5 fwd/1k, EN 0 | Source prior alone found acceptable RU memes but no breakouts; superseded by v4/v5/v5f scoring |
| 2026-10-30 | [viral_shares_blender_v1](2026-08-09-viral-shares-blender-v1.md) | killed | clickers/1k 0.031 control vs 0.025 treatment (n 344/350 users, 426k/395k sends); invites 5 vs 7; user LR -2.2 pp; engine was 0.76% of treatment sends | Ranking by past share clicks did not raise sharing; the engine barely served, so the arms hardly differed |
| 2026-10-30 | [source_affinity_demote_v1](2026-08-09-source-affinity-demote.md) | shipped | weekly LR 32.6-36.1% post vs 30.7-33.5% pre, no send-volume cliff | Soft demote of majority-dislike sources is safe (+1-3 pp LR); hard-block was rejected (cuts ~57% of inventory offline) |
| 2026-10-30 | [onboarding_skip_countdown_v1](2026-09-07-onboarding-skip-countdown.md) | shipped | p50 to first meme 11.6 s to 2.8 s; first tap flat (H10 control 60.0% vs ~61.5% pre) | A faster first meme alone does not raise first tap; kept as UX debt removal |
| 2026-10-30 | [meme_like_count](2026-05-12-meme-like-count.md) | killed | user LR 45.59% vs 46.20%, reaction rate 83.40% vs 83.26%, active days/14d 0.85 vs 0.86 (n 6306/6208) | Like counts on the button do not change engagement; a plain heart is simpler and avoids popularity bias |
| 2026-10-30 | [first_meme_nudge](2026-04-28-first-meme-nudge.md) | killed | first tap 15.8% control vs 16.0% treatment (n 1526/1456); reached-5 +2.1 pp (z~1.8); user LR -3.1 pp; d1-7 return 5.0% vs 5.0% | The nudge did not move first tap; it ran 6 months as an orphan split with no registry entry, so register every split |
| 2026-10-30 | [crosspost_taste_cohort_v1](2026-08-10-crosspost-taste-cohort-shadow.md) | killed | f1k top vs bottom half 28.52 vs 28.72 (n=287); taste>=1 vs taste=0 28.62 vs 29.87 | A hand-picked taste cohort that looked good offline (lift 1.19) carried no live signal |
| 2026-10-30 | [crosspost_meme_level_v1](2026-08-10-crosspost-v4-and-taste-cohort.md) | shipped | hit rate 32.1% to 41.0% (+8.9 pp, z~2.4, n 299/373), f1k 26.2 to 28.9; manual posts also +3.4 f1k (channel drift) | Bot like volume, not like rate, predicts channel forwards; part of the lift is channel drift |
| 2026-10-30 | [cold_start_fresh_viral_v1](2026-09-07-cold-start-fresh-viral.md) | killed | first tap 60.0% control vs 48.5% treatment, blocked <1h 19 vs 27 (n 95/99) | For a first impression, all-time proven hits beat fresh memes |
| 2026-10-30 | [cold_start_first_impression_v2](2026-08-09-cold-start-floors.md) | shipped | first tap 61.5% to 62.0% (n=100 post), underpowered; no rollback trigger | Stricter quality floors did not measurably move first tap; kept as harmless |
| 2026-10-30 | [channel_hits_v1](2026-09-05-channel-hits.md) | killed | n 43/42 hosts; retained invitees 0 vs 1, new invitees 1 vs 4; host reactions vs baseline 0.95 vs 0.77; hosts active d7-13 79.1% vs 73.8% | Channel hits in the feed did not create retained invitees and may cut host activity; inconclusive per protocol |
| 2026-10-30 | [broadcast_reengagement_label](2026-08-09-broadcast-reengagement-label.md) | shipped | broadcast p50 sec-to-react 3.8-5.5k s vs feed 5.7 s | Push reactions are delayed opens; keep broadcast_* rows out of feed dwell and LR analysis |
| 2026-10-30 | [broadcast_reengagement_hq_pick](2026-08-09-broadcast-hq-pick.md) | shipped | 14d: 5,533 sends, LR 57.2%, react<1h 36.5%, queue fallback 0.4% (pre-HQ LR ~54%, n~39) | Affinity x like-rate is a solid default push meme |
| 2026-10-30 | [broadcast_channel_viral_pick](2026-09-07-broadcast-channel-viral-pick.md) | killed | pooled react<1h 26.9% vs HQ 36.5% (-9.6 pp); within-user (67) +6.9 pp at 1h but -5.4 pp LR; viral LR 5-20 pp below HQ in every stratum | Channel forwards do not make a better personal push; HQ affinity x LR wins on like rate |
| 2026-10-30 | [bot2channel_ml_lab_v1](2026-08-11-bot2channel-ml-lab.md) | killed | lifetime walk-forward HOLD (n=3889); live shadow corr -0.092 (n=363 posted), agreed vs disagreed f1k 29.01 vs 29.10 | A one-split offline win (lift 1.19) did not survive lifetime walk-forward or live shadow; require both before trusting a ranker |
| 2026-10-05 | [ocr_length_preference_v1](2026-09-06-ocr-length-preference-v1.md) | inconclusive | +5.78 pp (95% CI +3.80 to +7.88), support 25/36, but late OCR 23.1% > 5% gate: invalid | OCR coverage lag can invalidate text-feature readouts; check OCR freshness before reading them |
| 2026-09-07 | [onboarding_first_tap_v1](2026-09-07-onboarding-first-tap.md) | shipped | 90d to 2026-09-07: 402 got a meme, 252 reacted, 150 silent; empty start 61% vs share 71%; 2026-10-30: never-got-meme rose 3.1% to 12.6% | First tap is the onboarding leak; the 2026-10-30 rise came from the language picker (fixed by onboarding_default_language_v1) |
| 2026-08-09 | [skip_is_next_not_ban](2026-08-09-skip-is-next.md) | shipped | skip p50 4.7 s vs like 7.1 s; instant skip 19% vs like 9% (7d feed) | Treat skip as next, not dislike; no dwell-weight ship without an offline counterfactual |
| 2026-08-09 | [recently_liked_blender_v2](2026-05-09-recently-liked-blender-v2.md) | shipped | median session 18 vs 19 (+5.6%), global LR 63.33% vs 63.67%, median user LR 62.65% vs 71.08% (n ~371/409; 1000/arm gate never reached) | v1's -14 pp LR was an assignment failure (skipper imbalance 2.3x); stratify by user LR; recently_liked deserves more weight |
| 2026-07-29 | [cold_start_candidate_guardrails](2026-07-14-cold-start-candidate-filter.md) | shipped | reached-10 32.4% treatment (n=37) vs 11.1% concurrent control vs 26.8% baseline; reached-5 70.3% vs 44.4%; all guardrails pass | Dropping a few weak sources from early positions lifts new-user depth (directional, n=37); mostly validates guarded phase 1 |
| 2026-04-09 | [cold_start_v2](2026-03-26-cold-start-v2.md) | shipped | first-meme LR 0% to 33.3%, organic 10-meme reach 24.2% to 52.4% (n=84; 44.5% incl. Apr 1 spike), WAU 897 | Cold start should rank proven memes by raw like rate; lr_smoothed's user-bias correction empties the pool for new users |
| 2026-04-08 | [upload_promo_day1](2026-03-29-upload-promotion-day1.md) | killed | uploads 3.2% treatment vs 8.8% control; D1 retention 28.1% vs 28.6%; D7 never measured | A passive 'did you know' message does not create an upload habit and may reduce uploads; needs a CTA after a positive moment |
| 2026-03-26 | [unstarve_like_spread](2026-03-20-unstarve-like-spread.md) | shipped | engine sends 3,112 to 18,233 per 7d (5.9x), engine LR 51.1% to 42.5%, median session 18 to 19, continuation 97.7% | Meme age is not a quality signal; widening a high-LR engine trades some LR for volume and longer sessions |
| 2026-03-26 | [cold_start_3phase](2026-03-20-cold-start-3phase.md) | killed | first-meme LR 0% (28 new users), 10-meme reach 24.2%, cold_start_explore LR 18.8%; session 19 and WAU flat | New users with no taste signal need the globally best memes first, not the most varied ones |
| 2026-03-20 | [goat_engine_investigation](2026-03-20-goat-engine-investigation.md) | shipped | goat continuation 98.0% (best engine) while LR fell 44.6% to 16%, halving about every 3 days | A fixed top-N engine exhausts its pool per user; continuation can stay high while LR decays, so add a per-user recency filter |
