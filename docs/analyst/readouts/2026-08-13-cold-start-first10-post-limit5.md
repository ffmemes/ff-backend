# Cold-start first-10 readout (post queue limit=5)

**Date:** 2026-08-13  
**Fix under test:** PR #351 — `check_queue` uses `limit=5` while `nmemes_sent < 30` (deployed ~2026-08-11 19:42 UTC)  
**Cohort:** users whose **first-ever** `user_meme_reaction.sent_at` is in the last 7 days  
**SQL:** [`docs/analyst/cold-start-first10-post-limit5.sql`](../cold-start-first10-post-limit5.sql)

## Sample size (critical)

| Period | First-send users (7d) | New accounts (`user.created_at`) |
|--------|----------------------:|---------------------------------:|
| pre_fix  | 23 | 22 |
| post_fix | **4** | **4** |

Post-fix N is too small for causal claims. Treat engine-mix as directional; skip% is noisy.

## Headline first-10 quality

| Period | Users | Sends (f10) | Like% | **Skip%** | p50 user LR (f10) |
|--------|------:|------------:|------:|----------:|------------------:|
| pre_fix  | 23 | 144 | 22.8 | **77.2** | 0.22 |
| post_fix | 4  | 23  | 23.5 | **76.5** | 0.30 |

**Skip% essentially unchanged.** Fix did **not** move first-10 skip rate.

## Continuation

| Period | Reach ≥5 | Reach ≥10 | Reach ≥30 |
|--------|----------|-----------|-----------|
| pre_fix  | 56.5% | 43.5% | 4/23 |
| post_fix | 50% (2/4) | 25% (1/4) | 1/4 |

## Position curve (skip%)

Pattern is stable pre and post:

| rn | pre skip% | post skip% (tiny n) |
|---:|----------:|--------------------:|
| 1 | 46.7 | 33.3 (first meme OK) |
| 2 | 90.9 | 100 |
| 3–4 | 67–85 | 50 |
| 5–10 | mostly 70–100 | mostly **100** |

**First meme is fine; from #2 the feed collapses into skip.**

## Engine mix — the real finding

### First-10 engines

| Engine | pre n | pre skip% | post n | post skip% |
|--------|------:|----------:|-------:|-----------:|
| `cold_start_explore` | 20 | **42.9** | 3 | **0** |
| `cold_start_explore_guarded` | 101 | **82.5** | 10 | **77.8** |
| `cold_start_adapt` / `_guarded` | **0** | — | **0** | — |
| `text_light_lr_smoothed` | 0 | — | 7 | **100** |
| broadcast / other | few | high | few | — |

### pos 1–5 vs 6–10 (post_fix)

| Band | Dominant engines | Adapt? |
|------|------------------|--------|
| 1–5 | explore, explore_guarded, text_light | no |
| 6–10 | **still** explore_guarded + text_light + broadcast | **no adapt** |

### First meme (rn=1)

| Period | Main engine | Like% among reacted |
|--------|-------------|---------------------|
| pre | `cold_start_explore` (20/23) | **57%** |
| post | `cold_start_explore` (3/4) | **100%** (n=2 reacted) |

Unguarded explore is the only engine that works. **Guarded explore is the skip factory.**

## Why limit=5 did not introduce adapt in 6–10

Planner stages:

- CS1 explore: `nmemes_sent < 6`
- CS2 adapt: `6 ≤ nmemes_sent < 16`

`check_queue` refill with `limit=5` at `nmemes_sent=0…5` **still plans CS1 explore**.  
Adapt only starts when generation sees `nmemes_sent ≥ 6`.

Also `queue_length ≤ 8` + small batches can restack explore before the user crosses 6 sent.

**Conclusion:** smaller batches alone are not enough; need **position-aware or nmemes-aware engine switch inside the first batch**, or force refill that targets adapt once `nmemes_sent ≥ 6` and **clear remaining explore queue**.

## Candidate quality (meme_stats of f10)

| Period | p50 lr_smoothed | p50 raw LR |
|--------|----------------:|-----------:|
| pre | 0.124 | 0.61 |
| post | 0.149 | 0.59 |

Raw LR ~0.6 (majority like in population) but **session skip ~77%** → content is “crowd-ok” but wrong for *this* new user / boring / similar. Diversity: ~4–5 sources per first-10 (not single-source spam).

Post-fix top skip sources (tiny): `t.me/memeromicon`, `deep_iranian_web`, `bingusrepublic`. Guardrail list already blocks some VK/TG URLs; not these.

## Verdict

| Hypothesis | Result |
|------------|--------|
| limit=5 reduces first-10 skip% | **No** (77% → 76%, n=4) |
| limit=5 puts `cold_start_adapt` into pos 6–10 | **No** (0 adapt rows) |
| Unguarded explore is decent | **Yes** (first meme / explore like% high) |
| Guarded explore is bad | **Yes** (skip ~80%) |

## Recommended next experiments (ordered)

1. **Kill or soften explore_guarded for pos 2–5** — use unguarded explore (or higher raw LR floor) for entire CS1, not only rn=1.  
2. **Force adapt after meme 5:** when `nmemes_sent` hits 5–6, `clear_meme_queue` + generate with adapt (don’t serve leftover explore).  
3. **Raise quality floor** on guarded path if kept: raw LR ≥ 0.55–0.60 and/or min reactions higher (watch inventory).  
4. **Source diversity cap** in first 10 (max 1–2 per source) — secondary.  
5. Re-run this SQL in **7–14 days** when post_fix n ≥ 30.

## Re-run

```bash
# analyst_readonly
psql "$ANALYST_DATABASE_URL" -f docs/analyst/cold-start-first10-post-limit5.sql
```
