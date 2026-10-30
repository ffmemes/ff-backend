# Experiment: Viral shares blender v1

Created: 2026-08-09  
Status: **completed — KILL (2026-10-30)**  
Owner: engineer / analyst  
Deployed: 2026-08-09 (~14:20 UTC first assignment)  
**Measure after: 2026-08-16** (primary)  
**Final if underpowered: 2026-08-23**  
Smoke: 2026-08-12  

Living registry: [`../HYPOTHESES.md`](../HYPOTHESES.md) **H1**.

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
  decide at day-14 (see HYPOTHESES.md)

## Primary metrics

1. Unique non-self share clickers (`user_deep_link_log` m_/s_) per 1k memes sent
2. New-user invites (`user.inviter_id`) per 1k memes sent

## Guardrails

- p50 session length (30m gap) — kill if treatment &lt; control − 10% relative
- Like rate — kill if treatment &lt; control − 5 pp (with enough volume)
- Engine continuation@30m for `viral_shares` vs `lr_smoothed`

## Ship / kill rules

See **H1 Decision rules** in `experiments/HYPOTHESES.md`.

## Interim (2026-08-09 15:44 UTC)

Full numbers: `docs/analyst/readouts/2026-08-09-viral-shares-interim.md`

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

Readout: [`docs/analyst/readouts/2026-10-30-experiment-closure.md`](../../docs/analyst/readouts/2026-10-30-experiment-closure.md).
The canned SQL §4 invite multiplier bug was fixed in the same PR.

## Readout SQL

`docs/analyst/viral-shares-blender-v1.sql`
