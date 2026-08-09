# Viral shares blender v1 — interim (not a closeout)

**When:** 2026-08-09 15:44 UTC (~1.4h after first assignment)  
**Experiment:** `viral_shares_blender_v1`  
**Verdict:** **HOLD** — underpowered; do not ship or kill.

Canonical schedule + decision rules: [`experiments/HYPOTHESES.md`](../../../experiments/HYPOTHESES.md) **H1**.

## Enrollment

| variant | n_users | first_assigned (UTC) |
|---------|---------|----------------------|
| control | 10 | 14:20 |
| treatment_viral_shares | 12 | 14:30 |

Sample gate in code (1000/arm) is **unrealistic** at current WAU; day-7 uses
≥80 users/arm or wait day-14 (see HYPOTHESES).

## Exposure

| variant | memes_sent | active_users | LR % | viral_shares sends | % viral |
|---------|------------|--------------|------|--------------------|---------|
| control | 297 | 10 | 39.6 | 0 | 0 |
| treatment | 367 | 12 | 54.2 | 13 | 3.5 |

Treatment LR higher is **noise** (tiny n). Engine is wired (13 sends).

## Primary metrics (growth)

| variant | unique non-self clickers | clickers/1k sends | new invites | invites/1k |
|---------|--------------------------|-------------------|-------------|------------|
| control | 0 | 0 | 0 | 0 |
| treatment | 0 | 0 | 0 | 0 |

Expected at this horizon.

## Guardrails (noisy)

| variant | sessions | p50 session length | mean |
|---------|----------|--------------------|------|
| control | 6 | 16.5 | 47.5 |
| treatment | 10 | 19.0 | 35.2 |

## Engine slice (7d global, viral only today)

| recommended_by | n | LR % | continuation@30m % |
|----------------|---|------|---------------------|
| lr_smoothed | 43 174 | 40.3 | 94.2 |
| recently_liked | 18 260 | 36.7 | 96.3 |
| es_ranked | 8 037 | 39.2 | 96.4 |
| viral_shares | 13 | 81.8 | 84.6 |

## Next actions

1. **2026-08-12** smoke (cohort, viral %, LR)  
2. **2026-08-16** primary readout → ship / hold / kill  
3. **2026-08-23** final if day-7 underpowered  
