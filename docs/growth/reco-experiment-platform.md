# Recommendation experiment platform (plan)

**Status:** design (2026-08-09)  
**Why:** WAU ~380, mature ~360 — online A/B is slow and underpowered. We need
offline/shadow eval on existing events + a thin experiment registry so hypotheses
are cheap to test and hard to mis-measure.

## Goals

1. **Playground** — run a candidate policy against historical `user_meme_reaction`
   rows without shipping code.
2. **Systemic experiments** — one registry, one assignment API, realistic sample gates.
3. **Reliable metrics** — primary + guardrails defined before ship; auto readout SQL.
4. **Less hardcode** — no more copy-pasted weight maps and silent `enabled=False`.

## Non-goals (v1)

- Full ML training loop / embeddings (later).
- Perfect multi-armed bandits.
- Replacing Prefect stats jobs.

---

## Architecture (3 layers, Reels/Twitter-shaped)

```
┌─────────────────────────────────────────────────────────┐
│  Generators (engines)                                   │
│  viral_shares | lr_smoothed | recently_liked | …        │
│  pure SQL → list[meme] + diagnostics                    │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│  Policies / filters (hard rules)                        │
│  unseen | language | block_disliked_sources | diversity │
│  shared SQL fragments in recommendations/utils.py       │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│  Allocator (blender + maturity plan + experiments)      │
│  plan = planner(nmemes_sent)                            │
│  weights = experiment_registry.apply(user, plan)        │
│  blend(candidates, weights)                             │
└─────────────────────────────────────────────────────────┘
```

Hard personalization (negative sources) lives in **policies**, not buried inside
one engine’s ORDER BY. Soft personalization (affinity multiply) stays in engines.

---

## Playground (offline eval)

### Location

```
src/recommendations/eval/
  metrics.py          # pure functions: LR, continuation, avoided-dislike rate
  replay.py           # load events, apply policy, score
scripts/reco_eval.py  # CLI: python scripts/reco_eval.py --policy block_disliked --days 7
```

### Inputs (from prod/analyst DB, read-only)

- `user_meme_reaction` (sent_at, reaction_id, recommended_by)
- `user_meme_source_stats` (at eval time — approx; true as-of needs history)
- `meme_stats`, `meme`, `user_language`

### Metrics (always the same set)

| Metric | Definition |
|--------|------------|
| **Like rate** | likes / (likes+dislikes) on evaluated impressions |
| **Avoided-dislike rate** | 1 − (dislikes / sends) among impressions policy would change |
| **Continuation@30m** | next send within 30m |
| **Blocked share** | % of historical sends that policy would have blocked |
| **Empty-pool risk** | % of refill moments with 0 candidates after policy |

### Modes

1. **Counterfactual filter** — “if block_disliked had been on, which past sends vanish; what was their LR?”
2. **Shadow rank** — re-score a logged candidate set (when we start logging candidates)
3. **Engine ablation** — drop/add engine weight on a fixed date range (simpler blend replay)

### CLI sketch

```bash
# Impact of disliked-source block on last 7 days of real sends
python scripts/reco_eval.py counterfactual-block-disliked \
  --days 7 --min-reactions 5

# Output: blocked_pct, LR_of_blocked, LR_of_kept, est_session_impact
```

**Honesty:** without as-of source stats history, we use **current**
`user_meme_source_stats` as approximation (good enough for v1 triage).

---

## Experiment registry (online)

### Today’s pain

- Assignment helpers duplicated in `blender_experiments.py`
- Gates of 1000/arm with 360 mature actives
- Hard-disabled zombies (`text_light`)
- Weights copy-pasted vs planner SSOT (partially fixed)

### Target

```python
# src/recommendations/experiments/registry.py
EXPERIMENTS = {
  "viral_shares_blender_v1": ViralSharesBlenderV1(),
  "block_disliked_sources_v1": FeatureFlag("RECOMMENDATION_BLOCK_DISLIKED_SOURCES"),
}

class Experiment(Protocol):
    id: str
    sample_gate_per_arm: int  # default max(150, f(wau))
    def apply_weights(self, user_id, base_weights) -> dict: ...
    def apply_flags(self, user_id, flags) -> Flags: ...
```

Rules:

1. **One entrypoint** for mature weights: `get_mature_blend_weights_with_experiments`
2. **Base weights only from** `feed_turn.planner`
3. **Sample gate** = `min(1000, max(150, mature_wau // 2))` or fixed 14 days
4. **Ship path** = “close experiment” updates planner/flags, assignment returns constant

### Feature flags vs A/B

| Change type | Vehicle |
|-------------|---------|
| Clear safety (disliked sources) | **Default ON** + kill switch env |
| Weight / engine mix | A/B with registry |
| CTA copy | A/B via `delivery.py` + assignment |
| Risky demotions | Shadow 3–7d → A/B → ship |

---

## Measurement contract (every online experiment)

Before merge, required files:

1. `experiments/active/YYYY-MM-DD-name.md` — hypothesis, gates, kill rules  
2. `docs/analyst/<name>.sql` — primary + guardrails  
3. `recommended_by` or assignment variant for slice  

Primary metrics library:

- Session: median memes / session (30m gap)  
- Quality: LR, fast-dislike rate  
- Growth: non-self `m_`/`s_` clicks per 1k sends, new invites  
- Guardrails: block rate, empty queue rate  

---

## Roadmap

| Phase | Deliverable | Effort |
|-------|-------------|--------|
| **0 (this PR)** | `block_disliked_sources` policy in all engines + config kill switch | S |
| **1** | `scripts/reco_eval.py counterfactual-block-disliked` | S |
| **2** | Candidate-log sampling (top-K engines per refill) for true shadow rank | M |
| **3** | Experiment registry refactor (one apply path) | M |
| **4** | Soft scorer (affinity + virality + exploration budget) | L |
| **5** | Online bandit / learned rank (only after volume grows) | L |

---

## Relation to growth

Better source selection → less “I hate this channel” → longer sessions → more
share attempts. It does **not** replace CTA / cold-start / distribution.

Ship hard negative personalization first (cheap, high face-validity), then
playground so the next ranking ideas don’t each take a quarter of calendar time.
