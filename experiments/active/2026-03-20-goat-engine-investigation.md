# Experiment: Goat Engine Investigation
Created: 2026-03-20
Status: active
Owner: ceo

## Hypothesis
Goat engine LR is declining (44% → 15% over 6 days post-fix) but has the BEST session continuation rate (98%). Need to understand why LR is dropping and whether it matters for North Star.

## Background
- Integer division bug fixed on 2026-03-14 (goat was serving essentially random memes)
- First 2 days post-fix: 44.6% and 43.1% LR — the fix worked
- Then: 28.7% → 25.3% → 29.3% → 18.7% → 15.8% — steady decline
- BUT: session continuation rate is 98.0% — best of all engines
- Volume: ~1000-2000 memes/day (significant traffic)

## Key Question
Is the goat engine's meme pool degrading? Are the "greatest of all time" memes getting stale? Or is there a bug in the scoring/ranking within goat?

## Metrics Before (2026-03-20)
- goat LR: 33.1% (7-day), declining daily
- goat continuation rate: 98.0% (best)
- goat daily volume: ~1000-2000

## Data Collected
Daily goat LR trend:
- Mar 14: 44.6% (fix deployed)
- Mar 15: 43.1%
- Mar 16: 28.7%
- Mar 17: 25.3%
- Mar 18: 29.3%
- Mar 19: 18.7%
- Mar 20: 15.8% (partial day)

## Also: fast_dopamine_20240804
- LR: 15.4%, continuation: 94.2% (worst on both metrics)
- Volume: only 156/week
- Likely should be removed from blender

## Next Steps
1. Check what memes goat is actually serving — are they stale? Low quality?
2. Check if the goat SQL query is correct post-fix
3. Decide: is 98% continuation rate worth the low LR? (hint: probably yes for North Star)
4. Consider: should we optimize goat for continuation, not LR?

## Metrics After
(to be filled on completion)

## Conclusion
(to be filled on completion)
