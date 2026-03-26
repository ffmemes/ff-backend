# Experiment: es_ranked engine (engagement_score-based ranking)

**Deployed**: 2026-03-16 (commit `38b5a06`)

## What we changed

Added `es_ranked` engine to the blender — ranks memes by `engagement_score * user_source_affinity` instead of `lr_smoothed`. Split goat's weight to create a direct A/B:

| Stage | Engine | Old weight | New weight |
|-------|--------|-----------|------------|
| Growing (30-100) | goat | 0.2 | 0.1 |
| Growing (30-100) | es_ranked | — | 0.1 |
| Mature (100+) | goat | 0.2 | 0.1 |
| Mature (100+) | es_ranked | — | 0.1 |

Cold start (<30 memes) is unchanged.

## Key difference: engagement_score vs lr_smoothed

| Signal | lr_smoothed | engagement_score |
|--------|-------------|------------------|
| Like | +1 | +1.0 |
| Dislike (fast ≤3s) | -1 | **-0.5** (skip/next tap) |
| Dislike (slow >3s) | -1 | -1.0 (genuine rejection) |
| Skip (no reaction) | ignored | **-0.3** |
| User bias | running avg | running avg |

The ⬇️ button is "next meme" not "dislike" — fast taps are skips, not rejections.

## Hypothesis

es_ranked should outperform goat on:
- **Like rate**: 70K candidates all have positive engagement_score (pre-filtered quality)
- **Session continuation**: more forgiving of "lazy next" taps → better meme diversity
- **Reaction rate**: fewer skips (memes people actually engage with)

es_ranked may underperform goat on:
- Diversity (simpler scoring, no source/timing/sharing bonuses like goat)

## Candidate pool comparison

| Engine | Candidates | Query time |
|--------|-----------|------------|
| lr_smoothed | 172,436 | ~100ms |
| es_ranked | 69,927 | 126ms |
| goat | all ok memes with source stats | ~200ms |
| like_spread_and_recent | 72 (starved!) | ~50ms |

## How to measure (run after 7 days: 2026-03-23)

```sql
-- Per-engine metrics (post-deploy)
SELECT
    recommended_by,
    count(*) as reactions,
    round(100.0 * count(*) FILTER (WHERE reaction_id = 1) / count(*), 1) as like_rate,
    round(100.0 * count(*) FILTER (WHERE reaction_id = 2) / count(*), 1) as skip_rate,
    round(100.0 * count(*) FILTER (WHERE reaction_id IS NULL) / count(*), 1) as no_reaction_pct,
    round(avg(EXTRACT(EPOCH FROM reacted_at - sent_at)) FILTER (
        WHERE EXTRACT(EPOCH FROM reacted_at - sent_at) BETWEEN 0.5 AND 60
    ), 1) as avg_sec_to_react
FROM user_meme_reaction UMR
WHERE UMR.sent_at > '2026-03-16'
  AND UMR.sent_at <= '2026-03-23'
  AND UMR.recommended_by IS NOT NULL
GROUP BY recommended_by HAVING count(*) > 10
ORDER BY reactions DESC;

-- Session continuation by engine: did user continue after seeing this engine's meme?
WITH ordered AS (
    SELECT
        user_id, meme_id, recommended_by, sent_at,
        LEAD(sent_at) OVER (PARTITION BY user_id ORDER BY sent_at) as next_sent_at
    FROM user_meme_reaction
    WHERE sent_at > '2026-03-16' AND sent_at <= '2026-03-23'
)
SELECT
    recommended_by,
    count(*) as total,
    round(100.0 * count(*) FILTER (
        WHERE next_sent_at IS NOT NULL
          AND next_sent_at - sent_at < interval '30 minutes'
    ) / count(*), 1) as continuation_pct
FROM ordered
WHERE recommended_by IS NOT NULL
GROUP BY recommended_by HAVING count(*) > 10
ORDER BY continuation_pct DESC;
```

## Success criteria

| Metric | goat baseline (2-day) | es_ranked target |
|--------|----------------------|-----------------|
| Like rate | 43.1% | ≥43% (non-inferior) |
| Reaction rate | TBD | higher than goat |
| Avg sec_to_react | ~9.2s | similar or higher (= more engagement) |
| Session continuation | TBD | higher than goat |
