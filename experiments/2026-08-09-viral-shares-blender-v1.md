---
id: viral_shares_blender_v1
status: killed
hypothesis: 0.2 weight on a viral_shares engine in the mature blend raises non-self share clickers and invites per 1k sends
primary_metric: unique non-self share clickers per 1k sends
guardrails: p50 session >= control - 10%, LR >= control - 3 pp
unit: user
variants: control:50,treatment:50
started: 2026-08-09
check_on: 2026-08-16
decided: 2026-10-30
result: clickers/1k 0.031 control vs 0.025 treatment (n 344/350 users, 426k/395k sends); invites 5 vs 7; user LR -2.2 pp; engine was 0.76% of treatment sends
learning: Ranking by past share clicks did not raise sharing; the engine barely served, so the arms hardly differed
code: candidates.viral_shares, src/recommendations/blender_experiments.py (assignment removed)
readout: docs/analyst/readouts/2026-10-30-experiment-closure.md
---

# Experiment: Viral shares blender v1

Created: 2026-08-09  
Status: **completed — KILL (2026-10-30)**  
Owner: engineer / analyst  
Deployed: 2026-08-09 (~14:20 UTC first assignment)  
**Measure after: 2026-08-16** (primary)  
**Final if underpowered: 2026-08-23**  
Smoke: 2026-08-12  

Registry entry H1: see the end of this file.

## Hypothesis

Injecting a dedicated `viral_shares` engine (memes ranked by share-click /
invite conversion) into the mature blend at weight **0.2** (stolen from
`lr_smoothed`) increases unique **non-self** share clickers and new-user
invites per 1k memes sent without reducing session depth (p50 memes/session).

## Changes Made

- Engine: `src/recommendations/candidates.py::viral_shares`
- Experiment: `viral_shares_blender_v1` in `src/recommendations/blender_experiments.py`
- Wiring: mature path uses `get_mature_blend_weights_with_experiments`
- Delivery prep seam: `src/tgbot/senders/delivery.py`
- Crosspost fix: share-click CTEs accept both `m_` and `s_` deep links

## Assignment

- Eligible: mature users via mature blend path (`nmemes_sent ≥ 100`)
- Strategy: `sha256(experiment_id:user_id) % 2`
- Control: base mature weights (after recently_liked v2 default)
- Treatment: base + `viral_shares: 0.2`, `lr_smoothed` reduced by 0.2
- Code constant `SAMPLE_GATE_PER_VARIANT = 1000` is **legacy**; decision sample
  for this WAU is **≥80 users/variant and ≥2k sends/variant** at day-7, else
  decide at day-14 (see H1 decision rules below)

## Primary metrics

1. Unique non-self share clickers (`user_deep_link_log` m_/s_) per 1k memes sent
2. New-user invites (`user.inviter_id`) per 1k memes sent

## Guardrails

- p50 session length (30m gap) — kill if treatment &lt; control − 10% relative
- Like rate — kill if treatment &lt; control − 5 pp (with enough volume)
- Engine continuation@30m for `viral_shares` vs `lr_smoothed`

## Ship / kill rules

See **H1 Decision rules** below.

## Interim (2026-08-09 15:44 UTC)

Full numbers: interim readout removed 2026-10-31 (in git history); final numbers in [`docs/analyst/readouts/2026-10-30-experiment-closure.md`](../docs/analyst/readouts/2026-10-30-experiment-closure.md)

- 10 control / 12 treatment users; 0 share clickers; 0 invites
- 13 `viral_shares` sends on treatment (wiring OK)
- **Verdict: HOLD**

## Metrics Before / After

| Window | control n | treatment n | clickers/1k C/T | invites/1k C/T | p50 session C/T | Decision |
|--------|-----------|-------------|-----------------|----------------|-----------------|----------|
| 2026-08-09 interim | 10 | 12 | 0 / 0 | 0 / 0 | 16.5 / 19.0 | HOLD |
| 2026-10-30 day-82 (final) | 344 | 350 | 0.031 / 0.025 | 0.012 / 0.018 | 14 / 10 (pooled) | KILL |

## Conclusion

**KILL (2026-10-30).** Enrollment stopped in code; every mature user gets the
shipped default blend (`MATURE_BLEND_WEIGHTS`). Existing assignment rows stay
for readouts. The `viral_shares` engine stays in `candidates.py` but no blend uses it.

- Primary failed: unique non-self share clickers per 1k sends 0.031 control vs
  0.025 treatment (13 vs 10 clickers, 426k / 395k sends).
- Invites 5 vs 7 (0.012 vs 0.018 per 1k). One treatment inviter accounts for 4, so this is noise.
- Mean per-user LR 49.7% vs 47.5% (−2.2 pp, inside the 3 pp guardrail).
- The engine reached only 0.76% of treatment sends, so the arms barely differed.
- Pooled p50 session dropped 14 → 10, which trips the frozen kill trigger. The
  user-level median of per-user p50 is flat (10 vs 10), so the drop is
  heavy-user composition. It is not why we killed the test.

Readout: [`docs/analyst/readouts/2026-10-30-experiment-closure.md`](../docs/analyst/readouts/2026-10-30-experiment-closure.md).
The canned SQL §4 invite multiplier bug was fixed in the same PR.

## Readout SQL

`docs/analyst/viral-shares-blender-v1.sql` (removed 2026-10-31; in git history)


## Registry entry (moved from docs/growth/HYPOTHESES.md, 2026-10-31)

## H1 — `viral_shares` in mature blend (A/B)

| Field | Value |
|-------|--------|
| **ID** | `viral_shares_blender_v1` |
| **Status** | **KILLED 2026-10-30**: clickers/1k C 0.031 vs T 0.025. Enrollment stopped, all users on control |
| **Shipped** | 2026-08-09 ~14:20 UTC (first assignment) |
| **Code** | `candidates.viral_shares`, `blender_experiments.get_viral_shares_blender_v1_weights` |
| **Note** | `2026-08-09-viral-shares-blender-v1.md` |
| **SQL** | removed 2026-10-31 (killed; in git history) |
| **Readout log** | removed 2026-10-31 (killed; in git history); final numbers in the 2026-10-30 closure readout |

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
