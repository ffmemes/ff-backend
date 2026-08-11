# Living hypotheses & check-in schedule

**Purpose:** When an agent (or human) resumes after days/weeks, this file answers:
what is live, what we expected, when to re-measure, and what “good / kill” means.

**Last updated:** 2026-08-11 (UTC) — H8 bot→channel offline ML lab  
**Prod DB clock at last interim:** `2026-08-10 ~17 UTC` (v4 early WATCH; H7 not yet deployed)

How to use on resume:

1. Read this file top → bottom.
2. For each row with `Next check ≤ today`, run the linked SQL against
   `ANALYST_DATABASE_URL` (read-only).
3. Write numbers into the linked readout path; update **Status** / **Decision**.
4. If status becomes `ship` or `kill`, open a code PR (planner weights / freeze
   enrollment) and move the experiment note `active/` → `completed/`.

---

## Check calendar (hard dates)

| Date (UTC) | What to run | Hypotheses |
|------------|-------------|------------|
| **2026-08-12** | Smoke + mature v4 if n≥8 | H1, H2, H3b, H5, **H6** |
| **2026-08-16** | Primary feed/reco day-7 | H1, H2, H3b, H5 |
| **2026-08-17** | **Crosspost v4 mature keep/kill** | **H6** |
| **2026-08-23** | Feed exp finals if needed | H1 primarily |
| **2026-08-24** | Taste shadow readout | **H7** |
| Ad-hoc | Bot→channel ML re-run / walk-forward | **H8** |
| Ad-hoc | After any ranking/deploy incident | all active |

Agent prompt on resume (copy-paste):

```text
Read experiments/HYPOTHESES.md. For every hypothesis with Next check ≤ today,
run the readout SQL on ANALYST_DATABASE_URL, update the Status/Decision rows
and the linked readout markdown, then recommend ship/hold/kill with numbers.
```

---

## H1 — `viral_shares` in mature blend (A/B)

| Field | Value |
|-------|--------|
| **ID** | `viral_shares_blender_v1` |
| **Status** | **active — too early to close** (interim only) |
| **Shipped** | 2026-08-09 ~14:20 UTC (first assignment) |
| **Code** | `candidates.viral_shares`, `blender_experiments.get_viral_shares_blender_v1_weights` |
| **Note** | `experiments/active/2026-08-09-viral-shares-blender-v1.md` |
| **SQL** | `docs/analyst/viral-shares-blender-v1.sql` |
| **Readout log** | `docs/analyst/readouts/2026-08-09-viral-shares-interim.md` |

### Hypothesis (precise)

Giving mature users (`nmemes_sent ≥ 100`) weight **0.2** on engine
`viral_shares` (memes ranked by `invited_count / ln(nmemes_sent+e)`), taken from
`lr_smoothed`, increases **unique non-self share clickers per 1k sends** and
**new-user invites per 1k sends** vs control, without harming session depth.

### Interim baseline (2026-08-09 15:44 UTC, ~1.4h)

| Variant | n_users | memes_sent | LR % | viral_sends | clickers/1k | invites/1k | p50 session |
|---------|---------|------------|------|-------------|-------------|------------|-------------|
| control | 10 | 297 | 39.6 | 0 | 0 | 0 | 16.5 |
| treatment | 12 | 367 | 54.2 | 13 (3.5%) | 0 | 0 | 19.0 |

**Do not decide from this.** n≪gate; 0 growth events expected in first hours.
Engine is live (13 sends, high LR noise).

### Decision rules (day-7 / day-14)

**Sample (realistic for WAU~380):**  
Do **not** wait for 1000/arm (unrealistic). Prefer:

- day-7 if **≥80 users/variant** and **≥2k sends/variant**, else hold to day-14;
- day-14 decide even if underpowered (ship only if direction clear + guardrails OK).

**Ship treatment → mature default** if all:

1. `unique_clickers_per_1k_sends` treatment ≥ control **and** absolute lift makes
   sense at our volume (or invites/1k clearly higher);
2. Guardrail: p50 session length treatment ≥ control − **10%** relative;
3. Guardrail: like rate treatment ≥ control − **3 pp**;
4. Engine slice: `viral_shares` continuation@30m not &lt; lr_smoothed − **5 pp**
   (on ≥100 viral sends).

**Kill (remove weight, freeze enrollment to control)** if:

- session p50 drops &gt;10% relative, or
- LR drops &gt;5 pp with ≥2k sends/arm, or
- day-14 still ~0 viral_engine exposure on treatment (wiring bug).

**Hold** if underpowered or metrics mixed.

### Next check

- **2026-08-12** smoke: cohort sizes, viral % of treatment sends, LR  
- **2026-08-16** primary  
- **2026-08-23** final if needed  

---

## H2 — Soft demote majority-dislike sources

| Field | Value |
|-------|--------|
| **ID** | `source_affinity_demote_v1` (config flags, not A/B) |
| **Status** | **shipped default ON** (PR #340) |
| **Shipped** | 2026-08-09 deploy `687fd46a` |
| **Code** | `RECOMMENDATION_DEMOTE_*`, `disliked_source_demote_sql` |
| **SQL** | `docs/analyst/source-affinity-demote-guardrails.sql` + inventory section of `dwell-feed-vs-broadcast.sql` |
| **Baseline** | `docs/analyst/readouts/2026-08-09-dwell-and-source-demote-baseline.md` |

### Hypothesis

Deprioritizing sources with `ndislikes > nlikes` (n≥5) by score ×0.15 increases
feed quality (higher session continuation / slightly higher LR on demotable
traffic) **without** increasing empty-queue symptoms, unlike hard-block (~57%
inventory cut offline).

### Decision rules (day-7)

**Keep ON** if:

1. Sends/day and active users not cliffing vs week before deploy;
2. Global like rate not down &gt;3 pp vs pre-deploy 7d window;
3. No spike in empty-queue alerts (Sentry/logs: `has empty meme queue`).

**Tune** multiplier (0.15 → 0.3) if LR up but users complain of “same sources”.  
**Disable** (`RECOMMENDATION_DEMOTE_DISLIKED_SOURCES=false`) if empty-queue or
volume collapse.

### Next check

- **2026-08-12** smoke volume/LR  
- **2026-08-16** full guardrails vs baseline  

---

## H3 — Broadcast delivery label for dwell analytics

| Field | Value |
|-------|--------|
| **ID** | `broadcast_reengagement_label` |
| **Status** | **shipped** — labels live (39 rows within hours of #340) |
| **Shipped** | 2026-08-09 with #340 |
| **Code** | `flows/broadcasts/meme.py` → `recommended_by=broadcast_*` |
| **SQL** | `docs/analyst/broadcast-reengagement.sql`, dwell SQL |

### Hypothesis

Labeling retention pushes separately from feed engines lets us measure true
in-session `sec_to_react` and optimize broadcast timing for **fast** reaction.

### Success criteria

1. ✅ Labeled rows exist (`broadcast_reengagement` / `_hq`)
2. Broadcast p50 `sec_to_react` **higher** than feed (delayed opens expected)
3. Share of broadcast reactions with `sec_to_react > 1h` documented

### Next check

- **2026-08-12 / 16** — full feed vs broadcast dwell table

---

## H3b — High-quality meme pick for retention broadcasts

| Field | Value |
|-------|--------|
| **ID** | `broadcast_reengagement_hq_pick` |
| **Status** | **shipping** (this PR) |
| **Code** | `src/recommendations/broadcast_pick.py`, kill switch `BROADCAST_HIGH_QUALITY_PICK_ENABLED` |
| **Labels** | `broadcast_reengagement_hq` (SQL pick) vs `broadcast_reengagement` (queue fallback) |
| **SQL** | `docs/analyst/broadcast-reengagement.sql` |

### Hypothesis

Choosing the reengagement meme by **user×source affinity × raw like rate**
(avoiding majority-dislike sources) beats blind feed-queue pop on:

1. **react_within_1h %** (primary — “came back because of this push”)
2. like rate among reacted
3. p50 `sec_to_react` among in-window reactions (secondary)

### Pre-HQ baseline (2026-08-09, ~39 `broadcast_reengagement` sends)

- like rate ~54% (small n)
- only ~4 reacts under 2 minutes — delayed open is the norm

### Decision rules (day-7 from HQ deploy)

**Keep HQ ON** if:

- `broadcast_reengagement_hq` react_within_1h ≥ queue-fallback **or** ≥ pre-HQ baseline + directionally better LR;
- no send failure spike (empty HQ → fallback should keep volume).

**Disable** (`BROADCAST_HIGH_QUALITY_PICK_ENABLED=false`) if HQ pool empty for
most users (fallback rate &gt;80%) or LR collapses &gt;5 pp vs fallback.

### Next check

- **2026-08-12** smoke: any `_hq` rows? fallback share?  
- **2026-08-16** primary HQ vs fallback vs feed  

---

## H4 — Skip ≠ hate (measurement contract, not a ship)

| Field | Value |
|-------|--------|
| **ID** | `skip_is_next_not_ban` |
| **Status** | **accepted product doctrine** |
| **Evidence** | skip p50 4.7s vs like 7.1s; instant skip 19% vs like 9% (7d feed) |
| **SQL** | `docs/analyst/dwell-feed-vs-broadcast.sql` |

### Hypothesis (ongoing)

Dislike button is primarily “next”; ranking must prefer **likes + dwell**, not
raw skip counts as bans. Future work: down-weight `sec_to_react < 2s` skips and
ignore `>1h` reactions in affinity.

### Next check

- **2026-08-16** re-run dwell percentiles; compare to baseline readout  
- No ship decision until a dedicated dwell-weight PR with offline counterfactual  

---

## H5 — Cold-start first-session quality floors

| Field | Value |
|-------|--------|
| **ID** | `cold_start_first_impression_v2` |
| **Status** | **shipping** (this PR) |
| **Code** | `cold_start_explore` raw-LR floor; CS3 blend → `best_uploaded` + text-light |
| **SQL** | engine slice in `docs/analyst/metrics.sql` / cold_start quality scripts |

### Hypothesis

**A1.** Raising `cold_start_explore` floors (raw like rate ≥0.50, ≥25 reactions,
order by `lr_smoothed`) lifts first-10 LR and reached-10 vs pre-change
(guarded explore was ~**18%** LR on 7d — too weak for first impression).

**A2.** CS3 (memes 16–29) replacing `like_spread` with `best_uploaded_memes`
improves LR/continuation in that band without starving personalization
(`cold_start_adapt` stays fixed_pos 0).

### Decision rules (day-7)

**Keep** if first-10 LR for `cold_start_explore*` ≥ pre-change + directionally
higher reached-5/10; no empty-queue spike for new users.

**Rollback explore floors** if explore pool empty → fallback share spikes and
session depth drops.

**Rollback CS3** if `best_uploaded` share causes lower continuation vs prior
week CS3 band.

### Next check

- **2026-08-12** smoke: explore volume + LR  
- **2026-08-16** first-10 / CS3 band metrics  

---

## H6 — Crosspost RU: meme-level bot volume (not LR) × source prior

| Field | Value |
|-------|--------|
| **ID** | `crosspost_meme_level_v1` / **score_version=4** |
| **Status** | **SHIPPING** (RU scheduled ranker default ON) |
| **Kill switch** | `CROSSPOST_RU_MEME_LIKE_VOLUME_ENABLED=false` → v2 |
| **Readout offline** | `docs/analyst/readouts/2026-08-09-crosspost-meme-level-offline.md` |
| **Readout online** | `docs/analyst/crossposting-v4-like-volume.sql` |
| **n offline** | 611 RU image posts / 120d |

### Hypothesis

Among channel candidates, **like volume** (`ln(nlikes+1)` via `meme_stats`) improves
24h channel forwards beyond source prior. Bot **like rate** does not.

### Offline result (2026-08-09)

- pre_lr vs channel: ~0 (reject LR feature)
- pre_likes residual Spearman ~**0.16–0.20**
- top-20% **src × log1p(pre_likes)** lift **1.14×** forwards (time-split test too)
- HIT: f1k ≥ **~31** OR forwards ≥ **12**

### Production formula (score_version=4)

```text
v2_score * LN(COALESCE(nlikes,0) + 1)
```

Logged in decision candidates: `like_volume_factor`, `like_volume_enabled`.

### Online success (7–14d after deploy)

Compare v4 mature posts vs last 30d v2 baseline:

- hit_rate_pct not down; preferably **+3pp**
- avg forwards_24h ≥ v2 baseline
- avg views_24h not &lt; v2 − 15%
- Kill if hit_rate collapses or empty slots spike

### Online early (2026-08-10 ~17 UTC)

- 4 v4 posts live; **0 mature** yet — WATCH
- age-matched ~6h: v4 f1k **30.0** vs v2 **32.6** (n=4, not RED)
- Frequency: **keep 5/day** (do not post more/less until mature readout)

### Next check

- **2026-08-12**: mature n≥8 if possible  
- **2026-08-17** (~7d): `crossposting-v4-like-volume.sql` keep/kill  
- Full plan: `experiments/active/2026-08-10-crosspost-v4-and-taste-cohort.md`

---

## H7 — Taste cohort soft signal (SHADOW)

| Field | Value |
|-------|--------|
| **ID** | `crosspost_taste_cohort_v1` |
| **Status** | **shadow only** — ranking unchanged |
| **Cohort** | `src/crossposting/data/ru_taste_cohort_v1.json` (top 50) |
| **Code** | `taste_cohort.py`, `_enrich_candidates_with_taste_shadow` |
| **SQL** | `docs/analyst/crossposting-taste-shadow.sql` |
| **Experiment note** | `experiments/active/2026-08-10-crosspost-v4-and-taste-cohort.md` |

### Hypothesis

A fixed set of ~50 users whose historical likes co-occur with high channel
fwd/1k provide a **weak but real** additional signal (soft boost), not a
replacement for like volume.

### Offline (2026-08-10)

- top50 likes top-20% lift **1.19** vs all-likes **1.10**; beats random-50 p95 **1.14**
- coverage ≥1 taste like ~**18%** of posts → never sole filter

### Shadow fields on decision candidates

`n_taste_likes`, `taste_boost_shadow` (= `1+0.15*min(n,5)`), `taste_cohort_version`

### Predictions

| Date | Pass if |
|------|---------|
| **2026-08-24** | Among mature picks with n_taste≥1, higher n_taste half has higher mean f1k (n≥20) |
| Canary | Only if H6 not RED and shadow pass → optional soft boost flag |

### Not doing

- Hardcode 50 users as only ranker  
- Post less often until H6 mature fails  

### Refresh

`python scripts/crosspost_taste_cohort.py`

---


---

## H8 — Bot→channel ML lab (OFFLINE)

| Field | Value |
|-------|--------|
| **ID** | `bot2channel_ml_lab_v1` |
| **Status** | **offline only** — no prod ranker change |
| **Code** | `experiments/ml-crosspost-bot2channel/` |
| **Note** | `experiments/active/2026-08-11-bot2channel-ml-lab.md` |
| **Report** | `experiments/ml-crosspost-bot2channel/reports/2026-08-11-models.md` |

### Hypothesis

Simple linear/logistic models on pre-post bot features + source prior beat
`ln(pre_likes+1)` on time-holdout top-20% f1k lift without tree overfit.

### First result (2026-08-11)

- n=624 labeled; single 70/30: logreg lift 1.187 vs v4 1.114 (looked good once)
- HGB depth3 **overfits** — discard for ship

### Walk-forward (authoritative, 2026-08-11)

- 3 expanding folds (~93 test each); bar: lift ≥ v4+0.05 on ≥2/3 + spearman gap &lt;0.25
- **logreg PASS** (2/3, mean lift 1.190 vs v4 1.080)
- **ridge PASS** (2/3, mean lift 1.171)
- HGB FAIL (overfit gap ~0.5)
- Report: `experiments/ml-crosspost-bot2channel/reports/2026-08-11-walkforward.md`
- RU summary: `.../reports/2026-08-11-otchet-ru.md`
- **No production pick change** — next is shadow score only


### Deep lifetime re-run (2026-08-11 evening)

- Telethon full crawl: 11928 msgs, 4897 sc_ joinable → dataset **n=3889** (2023-11..2026-08)
- Label = lifetime f1k (TG now); HIT = f1k≥train p75
- Walk-forward: **HOLD** — logreg/ridge/HGB do **not** beat v4 on ≥2/3 folds
- Source prior often ≥ volume on long history; bot volume ~flat on lifetime
- HTML: `experiments/ml-crosspost-bot2channel/reports/2026-08-11-results.html`
- Hypothesis battery: hybrids volume×source lead mean lift; **no bar PASS**
  (`reports/2026-08-11-hypothesis-battery.html`)

### Shadow hybrid in decision_log (shipping)

| Field | Value |
|-------|--------|
| **Status** | **shadow only** — pick unchanged |
| **Formula** | `shadow_score = ln(nlikes+1) * src_quality_mult` |
| **Version** | `v4_x_src_v1` (+ `shadow_score_maturity` band) |
| **Code** | `src/crossposting/shadow_score.py`, `_build_decision_log` |
| **SQL** | `docs/analyst/crossposting-shadow-hybrid.sql` |

Also logs `shadow_rank`, `shadow_pick_meme_id`, `shadow_vs_prod_disagree`.

### Next check

- After deploy: decision_log has `shadow_score` on candidates
- **2026-08-25**: `crossposting-shadow-hybrid.sql` — disagree rate + corr(shadow, f1k_24h)
- Canary soft boost only if live corr/lift clearly > v4 alone
- After H7 merge: re-export + optional taste feature
- Do not schedule as feed experiment


## Explicitly not open experiments

| Item | State |
|------|--------|
| `recently_liked_blender_v2` | **Shipped as mature default** (completed) |
| Hard-block majority-dislike | **Rejected** as default; opt-in flag only |
| Full Feed Turn rewrite | Not doing |
| New blender A/B | Do not start until H1 day-7 done |
| Crosspost rank by bot LR only | **Rejected** |
| Crosspost taste-only ranker | **Rejected** (coverage); soft boost only after H7 |
| Crosspost rank by bot LR | **Rejected** offline (H6) |

---

## Agent checklist (weekly resume)

```bash
# 1) Hypotheses file
# 2) Run:
psql "$ANALYST_DATABASE_URL" -f docs/analyst/viral-shares-blender-v1.sql
psql "$ANALYST_DATABASE_URL" -f docs/analyst/source-affinity-demote-guardrails.sql
psql "$ANALYST_DATABASE_URL" -f docs/analyst/dwell-feed-vs-broadcast.sql
psql "$ANALYST_DATABASE_URL" -f docs/analyst/broadcast-reengagement.sql
psql "$ANALYST_DATABASE_URL" -f docs/analyst/crossposting-v4-like-volume.sql   # H6
psql "$ANALYST_DATABASE_URL" -f docs/analyst/crossposting-taste-shadow.sql    # H7
# 3) Update this file Status/Decision + write
#    docs/analyst/readouts/YYYY-MM-DD-weekly-hypotheses.md
# 4) Crosspost plan tables:
#    experiments/active/2026-08-10-crosspost-v4-and-taste-cohort.md
```

Healthy product snapshot (rough, not ship gates):

- new_memes_24h &gt; 100, ok_pct ~90–96%
- active reactors 24h not collapsing vs prior week
- multi-engine mix still present (not 100% one engine)
