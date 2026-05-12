# Experiment: Meme Like Count in Reaction Button

**Deployed**: 2026-05-12

## What We Changed

Added a user-level A/B experiment for the private meme feed:

| Variant | Like Button |
|---------|-------------|
| `control` | Heart only, current behavior |
| `treatment` | Heart plus like count when `meme_stats.nlikes >= 5` |

Dislike counts stay hidden. Low-count memes stay visually neutral in treatment,
so fresh or niche memes do not get negative social proof from `0-4` likes.

## Hypothesis

Visible positive social proof may increase:
- explicit like rate
- reaction rate
- session continuation

Main risks:
- popularity bias toward already-proven memes
- lower honest preference signal from users who follow the crowd
- possible interaction with recommendation experiments

## Measurement

Primary read after each variant has at least 1,000 assigned users:

```sql
SELECT *
FROM v_meme_like_count_experiment_results
ORDER BY variant;

SELECT *
FROM v_meme_like_count_experiment_sample_gate
ORDER BY variant;
```

Primary metrics:
- `like_rate_pct`
- `explicit_reaction_rate_pct`
- `continuation_rate_pct`
- `median_memes_sent_per_user`

Guardrails:
- treatment like rate must not rise while continuation rate falls meaningfully
- treatment must not reduce explicit reaction rate
- check fresh/low-like meme exposure separately if popularity concentration rises

## Rollback

Disable the experiment by returning `control` from
`get_visible_meme_like_count()`, or revert the implementation. The migration only
adds read-only measurement views.
