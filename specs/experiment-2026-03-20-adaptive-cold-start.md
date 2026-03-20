# Experiment: Adaptive Cold Start (3-phase)

**Deployed**: 2026-03-20

## What we changed

Replaced the single-engine cold start (lr_smoothed → best_uploaded_memes fallback)
with a 3-phase adaptive approach:

| Phase | nmemes_sent | Engine | Strategy |
|-------|-------------|--------|----------|
| 1: Explore | 0-5 | `cold_start_explore` | Best meme from each top source (DISTINCT ON), data-driven source ranking |
| 2: Adapt | 6-15 | `cold_start_adapt` | Weight sources by raw reactions (like=+1, dislike=-0.5, floor=0.1) |
| 3: Transition | 16-30 | blend(adapt + lr_smoothed + like_spread) | 50/30/20 blend, adapt pinned at pos 0 |

Also changed:
- Queue threshold 2→8, batch 5→15
- Unstarved `like_spread_and_recent` (removed `age_days < 30` filter)

## Hypothesis

1. **First-5 churn drops**: diverse sources in Phase 1 → fewer "all wrong" first impressions
2. **Session length increases**: Phase 2 adapts within session → more relevant memes
3. **like_spread_and_recent usage increases**: from 72 to thousands of candidates

## Baseline (capture before measuring)

Run this BEFORE deploying to get pre-experiment baseline:

```sql
-- Cold start activation: what % of new users reach meme 10?
WITH first_users AS (
    SELECT user_id, MIN(sent_at) AS first_meme
    FROM user_meme_reaction
    WHERE sent_at > NOW() - INTERVAL '14 days'
    GROUP BY user_id
    HAVING COUNT(*) <= 30  -- only cold start users
)
SELECT
    count(*) AS total_new_users,
    round(100.0 * count(*) FILTER (WHERE reaction_count >= 5) / NULLIF(count(*), 0), 1) AS reach_5_pct,
    round(100.0 * count(*) FILTER (WHERE reaction_count >= 10) / NULLIF(count(*), 0), 1) AS reach_10_pct,
    round(100.0 * count(*) FILTER (WHERE reaction_count >= 30) / NULLIF(count(*), 0), 1) AS reach_30_pct,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY reaction_count) AS median_memes
FROM (
    SELECT FU.user_id, COUNT(*) AS reaction_count
    FROM first_users FU
    JOIN user_meme_reaction UMR ON UMR.user_id = FU.user_id
    GROUP BY FU.user_id
) sub;
```

## How to measure (run after 7 days)

```sql
-- Per-engine metrics for cold start engines
SELECT
    recommended_by,
    count(*) as reactions,
    round(100.0 * count(*) FILTER (WHERE reaction_id = 1) / count(*), 1) as like_rate,
    round(avg(EXTRACT(EPOCH FROM reacted_at - sent_at)) FILTER (
        WHERE EXTRACT(EPOCH FROM reacted_at - sent_at) BETWEEN 0.5 AND 60
    ), 1) as avg_sec_to_react
FROM user_meme_reaction UMR
WHERE UMR.sent_at > '2026-03-20'
  AND UMR.sent_at <= '2026-03-27'
  AND UMR.recommended_by IN ('cold_start_explore', 'cold_start_adapt', 'lr_smoothed')
GROUP BY recommended_by
ORDER BY reactions DESC;

-- Session continuation by cold start phase
WITH ordered AS (
    SELECT
        user_id, meme_id, recommended_by, sent_at,
        LEAD(sent_at) OVER (PARTITION BY user_id ORDER BY sent_at) as next_sent_at
    FROM user_meme_reaction
    WHERE sent_at > '2026-03-20' AND sent_at <= '2026-03-27'
)
SELECT
    recommended_by,
    count(*) as total,
    round(100.0 * count(*) FILTER (
        WHERE next_sent_at IS NOT NULL
          AND next_sent_at - sent_at < interval '30 minutes'
    ) / count(*), 1) as continuation_pct
FROM ordered
WHERE recommended_by IN ('cold_start_explore', 'cold_start_adapt', 'lr_smoothed')
GROUP BY recommended_by HAVING count(*) > 10
ORDER BY continuation_pct DESC;

-- Cold start activation (post-deploy, same query as baseline)
-- Compare reach_5_pct, reach_10_pct, median_memes

-- like_spread_and_recent candidate pool size (should be >> 72)
SELECT count(*) as candidates
FROM meme M
INNER JOIN meme_stats MS ON MS.meme_id = M.id
WHERE M.status = 'ok'
  AND MS.nlikes > MS.ndislikes
  AND MS.raw_impr_rank = 0;
```

## Success criteria

| Metric | Baseline | Target |
|--------|----------|--------|
| cold_start_explore LR | N/A (new) | ≥40% |
| cold_start_adapt LR | N/A (new) | ≥43% (match lr_smoothed) |
| Reach meme 10 % | ~55% (H4 data) | ≥60% |
| Session continuation (Phase 1) | TBD | ≥85% |
| like_spread_and_recent candidates | 72 | ≥1000 |

## Key design decisions (for future reference)

1. **Data-driven source selection** (not hardcoded) — works for any language
2. **Raw reactions in SQL CTE** (not stats tables) — bypasses 15-min delay
3. **Floor weight 0.1** (not zero) — ensures exploration even if all sources disliked
4. **70/30 exploit/explore** — standard multi-armed bandit safeguard
5. **LR as quality signal** — imperfect (good memes get disliked), engagement_score may be better for V2
6. **DISTINCT ON for diversity** — guarantees different sources in Phase 1

## Rollback

If cold start metrics regress: revert the commit. No schema changes needed.
If only one phase underperforms: adjust phase boundaries or weights in meme_queue.py.
