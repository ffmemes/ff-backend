# Experiment: Fix goat engine + preserve blender ordering + per-user seed

**Deployed**: 2026-03-14 02:17 UTC (commit `67d123f`)

## What we changed

### Fix 1: Goat engine integer division bug
PostgreSQL integer division truncated all scores to 0 for 100% of memes (186K).
The engine was serving random memes with negative lr_smoothed (-0.159 avg),
achieving 6.6% like rate and 5.1% sharing rate — worst of all engines.

**Fix**: Cast to `::float` before division.

### Fix 2: Redis SET → LIST
Queue used `SADD/SPOP` (random pop from set), destroying the blender's ordering.
`fixed_pos={0: "lr_smoothed"}` was meaningless — position 0 was random.

**Fix**: `RPUSH/LPOP` preserves insertion order.

### Fix 3: Per-user blender seed
`random.seed(42)` gave every user identical engine sampling order.
Also mutated global RNG state across async requests.

**Fix**: `random.Random(seed)` instance, `None` default (random per call).

## Hypothesis

These 3 fixes together should improve **session length** (north star) and **sharing rate**:

1. Goat goes from serving garbage (-0.159 lr_smoothed) to serving genuinely
   high-quality memes. Expected: goat like rate rises from 6.6% to ~45%+
2. Blender ordering now reaches users intact. `lr_smoothed` (best workhorse)
   is actually served first as intended.
3. Different users see different engine mixes, increasing diversity.

We do NOT expect a dramatic session-length jump because goat was only 0.4%
of traffic (604/156K reactions last 7 days). The bigger impact is fix 2+3:
blender ordering + diversity affect 100% of blended users (30+ memes sent).

## Baseline (7 days pre-fix)

| Metric | Value |
|--------|-------|
| Active users | 510 |
| Total sessions | 3,659 |
| Avg session length | 42.3 memes |
| Median session length | 20 memes |

### Per-engine (7 days pre-fix)

| Engine | Reactions | Like Rate | Sharing % |
|--------|--------:|----------:|----------:|
| lr_smoothed | 69,421 | 45.3% | 16.9% |
| low_sent_pool | 53,705 | 27.6% | 5.8% |
| recently_liked | 16,406 | 43.2% | 13.7% |
| best_uploaded_memes | 11,353 | 46.9% | 45.2% |
| like_spread_and_recent | 4,794 | 47.6% | 32.0% |
| goat | 604 | 6.6% | 5.1% |
| fast_dopamine | 317 | 18.9% | 26.8% |

## How to measure (run after 7 days: 2026-03-21)

```sql
-- Session metrics (post-fix)
WITH sessions AS (
    SELECT
        user_id, sent_at,
        CASE WHEN sent_at - LAG(sent_at) OVER (PARTITION BY user_id ORDER BY sent_at) > interval '30 minutes'
             OR LAG(sent_at) OVER (PARTITION BY user_id ORDER BY sent_at) IS NULL
             THEN 1 ELSE 0 END as is_new_session
    FROM user_meme_reaction
    WHERE sent_at > '2026-03-14 02:17:00'
      AND sent_at <= '2026-03-21 02:17:00'
),
session_ids AS (
    SELECT *, SUM(is_new_session) OVER (PARTITION BY user_id ORDER BY sent_at) as session_id
    FROM sessions
),
session_lengths AS (
    SELECT user_id, session_id, count(*) as memes_in_session
    FROM session_ids GROUP BY user_id, session_id
)
SELECT
    count(DISTINCT user_id) as active_users,
    count(*) as total_sessions,
    round(avg(memes_in_session), 1) as avg_session_length,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY memes_in_session) as median_session_length
FROM session_lengths WHERE memes_in_session >= 2;

-- Per-engine metrics (post-fix)
SELECT
    recommended_by,
    count(*) as reactions,
    round(100.0 * count(*) FILTER (WHERE reaction_id = 1) / count(*), 1) as like_rate,
    round(100.0 * count(*) FILTER (WHERE MS.invited_count > 0) / count(*), 1) as pct_shared
FROM user_meme_reaction UMR
LEFT JOIN meme_stats MS ON MS.meme_id = UMR.meme_id
WHERE UMR.sent_at > '2026-03-14 02:17:00'
  AND UMR.sent_at <= '2026-03-21 02:17:00'
  AND UMR.recommended_by IS NOT NULL
GROUP BY recommended_by HAVING count(*) > 10
ORDER BY reactions DESC;
```

## Success criteria

| Metric | Baseline | Target | Why |
|--------|----------|--------|-----|
| Goat like rate | 6.6% | >40% | Integer division fix makes scoring work |
| Goat sharing % | 5.1% | >15% | Better memes = more shares |
| Median session | 20 | ≥20 | Should not regress |
| Avg session | 42.3 | ≥43 | Modest improvement from better ordering |

## What's NOT measured by this experiment

- Cold start quality (<30 memes) — not affected by these changes
- Moderator experience — low_sent_pool unchanged
- Content supply — power users exhausting 62K meme pool is a separate problem

## Next steps (regardless of experiment outcome)

| Priority | Action | Why |
|----------|--------|-----|
| 1 | Fix SQL injection in candidates.py | Security: all engines use f-string interpolation |
| 2 | Optimize cold start with retention sources | 25% users leave in first 5 memes (H4) |
| 3 | Scale up winning engines | like_spread_and_recent (47.6% LR, 32% sharing) underutilized |
| 4 | Increase queue refill threshold 2→8 | Fast users exhaust queue before refill |
| 5 | Hourly stats instead of nightly | Stale lr_smoothed/source affinity = stale rankings |
| 6 | Content supply: add more sources | Power users running out of memes |
| 7 | Re-engagement push for tryout users | Converting 10-29 reaction users = +5pp LR |
