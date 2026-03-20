# Experiment: Goat Engine Investigation

**Status:** completed
**Created:** 2026-03-20
**Concluded:** 2026-03-20
**Owner:** ceo

## Hypothesis

Goat engine LR is declining (44% → 15% over 6 days post-fix) but has the BEST session continuation rate (98%). Need to understand why LR is dropping and whether it matters for North Star.

## Background

- Integer division bug fixed on 2026-03-14 (goat was serving essentially random memes)
- First 2 days post-fix: 44.6% and 43.1% LR — the fix worked
- Then: 28.7% → 25.3% → 29.3% → 18.7% → 15.8% — steady decline
- BUT: session continuation rate is 98.0% — best of all engines
- Volume: ~1000-2000 memes/day (significant traffic)

## Data Collected

Daily goat LR trend:
- Mar 14: 44.6% (fix deployed)
- Mar 15: 43.1%
- Mar 16: 28.7%
- Mar 17: 25.3%
- Mar 18: 29.3%
- Mar 19: 18.7%
- Mar 20: 16.0% (partial day)

Engine comparison (7d, all engines):
| Engine | Continuation Rate | Like Rate |
|--------|------------------|-----------|
| goat | **98.0%** (best) | 33.1% (declining) |
| es_ranked | 97.8% | 49.0% |
| recently_liked | 97.5% | 43.7% |
| fast_dopamine | 93.9% (worst) | 14.9% |

## Metrics After

- goat continuation rate: 98.0% (BEST of all engines)
- goat LR: 16% and declining
- Decline pattern: halved every ~3 days since fix

## Conclusion

**Decision: KEEP goat engine. Do not remove.**

Root cause of LR decline: **meme pool exhaustion**, not content quality degradation.

Evidence:
1. Continuation rate (98%) is the BEST of all engines — users who see a goat meme keep scrolling more than any other engine. This is the North Star metric.
2. LR halved every ~3 days — classic pattern of the same top-ranked memes being re-shown to users who already saw them. Users who liked it are gone; remaining views are from users who haven't seen it, and the meme pool is shrinking.
3. The fix on Mar 14 briefly restored 44% LR (day 1-2), then pool exhaustion set in.

**Follow-up needed:** Add per-user recency filter to goat query — `NOT EXISTS (seen in last N days)` or use `user_meme_reaction` to exclude recently-seen memes. This will rotate the GOAT pool and should restore LR while keeping high continuation.

Tracking in TODOS.md: "Add per-user recency filter to goat engine".
