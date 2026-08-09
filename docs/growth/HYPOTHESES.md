# Living hypotheses & check-in schedule

**Purpose:** When an agent (or human) resumes after days/weeks, this file answers:
what is live, what we expected, when to re-measure, and what “good / kill” means.

**Last updated:** 2026-08-09 (UTC) — added H5 cold-start + H3b HQ broadcast pick  
**Prod DB clock at last interim:** `2026-08-09 15:44 UTC`

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
| **2026-08-12** (day ~3) | Smoke only — not a ship decision | H1, H2, H3/H3b, H5 |
| **2026-08-16** (day ~7) | **Primary readout** | H1, H2, H3/H3b, H5 |
| **2026-08-23** (day ~14) | Final keep/kill if day-7 underpowered | H1 primarily; H3b/H5 if thin |
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
| **ID** | `crosspost_meme_level_v1` |
| **Status** | **offline PASS (partial)** — not in cron yet |
| **Readout** | `docs/analyst/readouts/2026-08-09-crosspost-meme-level-offline.md` |
| **n** | 611 RU image posts / 120d |

### Hypothesis

Among channel candidates, **timestamp-safe pre-post like volume** (and engaged likes)
improves 24h channel forwards **beyond source prior**. Bot **like rate** does not.

### Offline result (2026-08-09)

- pre_lr vs channel: ~0 (reject LR feature)
- pre_likes / engaged_likes residual Spearman ~**0.16–0.20**
- top-20% **src × log1p(pre_likes)** lift **1.14×** forwards (time-split test too)
- pre_share coverage **2.6%** only
- HIT threshold: f1k ≥ **~31** (p75) OR forwards ≥ **12**

### Next

1. Shadow-log meme score in `crossposting_decision_log` (no post change)
2. RU canary / score_version bump only after shadow confirms ranking flip quality
3. Optional ML only if beats `src × log1p(likes)` by ≥5% lift

### Next check

- After shadow deploy: weekly hit_rate + mean forwards vs v2 baseline  

---

## Explicitly not open experiments

| Item | State |
|------|--------|
| `recently_liked_blender_v2` | **Shipped as mature default** (completed) |
| Hard-block majority-dislike | **Rejected** as default; opt-in flag only |
| Full Feed Turn rewrite | Not doing |
| New blender A/B | Do not start until H1 day-7 done |
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
# 3) Update this file Status/Decision + write
#    docs/analyst/readouts/YYYY-MM-DD-weekly-hypotheses.md
```

Healthy product snapshot (rough, not ship gates):

- new_memes_24h &gt; 100, ok_pct ~90–96%
- active reactors 24h not collapsing vs prior week
- multi-engine mix still present (not 100% one engine)
