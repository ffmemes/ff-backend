# Closeout: recently_liked_blender_v2

**Decision date:** 2026-08-09  
**Verdict:** **SHIP treatment weights as mature default**  
**Experiment ID:** `recently_liked_blender_v2`

## Why close now

- Enrollment frozen since ~2026-07-22 (`RECENTLY_LIKED_BLENDER_V2_ENROLLMENT_FROZEN`).
- Sample gate of 1000/arm is **unreachable** with ~360 mature active users / week.
- Partial read at ~371 control / 409 treatment is directionally clear and guardrails hold.

## Results (post-assignment, up to 30d sends / 14d sessions)

| Metric | Control | Treatment | Delta |
|--------|---------|-----------|-------|
| Users with sends | 371 | 408 | — |
| Sends | 136 350 | 174 183 | more exposure |
| Global LR | **63.33%** | **63.67%** | **+0.34pp** |
| % traffic `recently_liked` | 16.9% | **22.9%** | +6pp (intended) |
| Median session (14d) | 18 | **19** | **+5.6%** (success bar was +5%) |
| Avg session | 37.2 | **50.0** | large |
| Median user LR (≥10 reacts) | 62.65% | **71.08%** | **+8.4pp** |
| High-volume skippers in arms | 0 | 0 | excluded arm=63 |

Skipper exclusion worked (v1 failure mode fixed).

## Decision

1. **Promote treatment blend to `MATURE_BLEND_WEIGHTS`** (SSOT in `feed_turn/planner.py`).
2. **Stop dual-path assignment** — `get_recently_liked_blender_v2_weights` returns shipped default only.
3. Mark experiment **completed** (not cancelled).
4. Keep historical assignment rows for archaeology; do not re-open with gate 1000.

## Learnings to keep

1. **Stratify by user 7d LR quartile** + exclude high-volume skippers before reading blend experiments.
2. **Sample gates must match WAU** (~200/arm or 14 days, not 1000) for this product scale.
3. **Increasing `recently_liked` for mature users can improve session without LR damage** when assignment is clean.
4. V1 failure was **design/imbalance**, not proof the engine is toxic.

## Shipped weights

```
best_uploaded_memes: 0.3
like_spread_and_recent_memes: 0.25
lr_smoothed: 0.35
recently_liked: 0.3
goat: 0.1
es_ranked: 0.1
```
