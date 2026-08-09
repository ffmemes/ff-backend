# Living hypotheses & check-in schedule

**Purpose:** When an agent (or human) resumes after days/weeks, this file answers:
what is live, what we expected, when to re-measure, and what “good / kill” means.

**Last updated:** 2026-08-09 (UTC)  
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
| **2026-08-12** (day ~3) | Smoke only — not a ship decision | H1 viral_shares, H2 demote |
| **2026-08-16** (day ~7) | **Primary readout** | H1, H2, H3 broadcast label |
| **2026-08-23** (day ~14) | Final keep/kill if day-7 underpowered | H1 primarily |
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
| **Status** | **shipped** (label on new retention pushes) |
| **Shipped** | 2026-08-09 with #340 |
| **Code** | `flows/broadcasts/meme.py` → `recommended_by=broadcast_reengagement` |
| **SQL** | `docs/analyst/dwell-feed-vs-broadcast.sql` sections 1–3, 6 |

### Hypothesis

Labeling retention pushes separately from feed engines lets us measure true
in-session `sec_to_react` and optimize broadcast timing for **fast** reaction
(not content affinity from stale opens).

### Success criteria (day-7+)

1. Rows with `recommended_by = 'broadcast_reengagement'` appear after ≥1
   scheduled reengagement run;
2. Broadcast p50 `sec_to_react` **higher** than feed (delayed opens expected);
3. Share of broadcast reactions with `sec_to_react > 1h` documented (exclude
   from affinity later).

### Next check

- **2026-08-12** — any labeled rows yet?  
- **2026-08-16** — full feed vs broadcast dwell table  

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

## Explicitly not open experiments

| Item | State |
|------|--------|
| `recently_liked_blender_v2` | **Shipped as mature default** (completed) |
| Hard-block majority-dislike | **Rejected** as default; opt-in flag only |
| Full Feed Turn rewrite | Not doing |
| New blender A/B | Do not start until H1 day-7 done |

---

## Agent checklist (weekly resume)

```bash
# 1) Hypotheses file
# 2) Run:
psql "$ANALYST_DATABASE_URL" -f docs/analyst/viral-shares-blender-v1.sql
psql "$ANALYST_DATABASE_URL" -f docs/analyst/source-affinity-demote-guardrails.sql
psql "$ANALYST_DATABASE_URL" -f docs/analyst/dwell-feed-vs-broadcast.sql
# 3) Update this file Status/Decision + write
#    docs/analyst/readouts/YYYY-MM-DD-weekly-hypotheses.md
```

Healthy product snapshot (rough, not ship gates):

- new_memes_24h &gt; 100, ok_pct ~90–96%
- active reactors 24h not collapsing vs prior week
- multi-engine mix still present (not 100% one engine)
