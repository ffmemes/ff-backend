# SPEC.md

## Product

Telegram meme recommendation bot (@ffmemesbot). Infinite personalized meme feed.
User presses /start -> receives meme with Like/Dislike buttons -> reaction triggers next meme.

**North star metric**: session length (memes per session). NOT like rate.

**Goal**: Viral growth through better memes -> better crossposting -> more users -> better signal -> better memes.

## Key Numbers (2026-03-13)

| Metric | Value |
|--------|-------|
| Total users | 22,421 |
| MAU | 876 |
| WAU | 530 |
| Total reactions | 22M |
| Total memes | 535K (205K with status='ok') |
| Meme sources | 750 |
| Like rate | 43.4% |
| Median session | 19 memes |
| D1 retention | 37.7% |
| D30 retention | 48.5% |

## Critical Flow

```
User taps Like/Dislike
  -> handle_reaction() saves reaction
  -> next_message() pops meme from Redis queue
  -> if queue low (<= 2): generate_recommendations(limit=5)
  -> 9 SQL engines blended by user maturity stage
  -> meme sent to user
```

## Data Flow

```
Sources (TG/VK/IG) -> Parsers (hourly) -> meme_raw_* tables
  -> ETL (filter, type detect) -> meme (status=created)
  -> Download + Watermark + Upload to TG -> telegram_file_id
  -> Ad filter + Dedup -> status='ok'
  -> Recommendation engines -> Blender -> Redis queue -> User
```

## Detailed Specs

See [specs/](specs/) for subsystem documentation:

| File | Scope |
|------|-------|
| [specs/recommendations.md](specs/recommendations.md) | Engines, blender, queue, maturity stages |
| [specs/reaction-flow.md](specs/reaction-flow.md) | Hot path: reaction -> next meme |
| [specs/parsing-etl.md](specs/parsing-etl.md) | Source parsing, ETL, status pipeline |
| [specs/dedup.md](specs/dedup.md) | Dedup mechanisms + improvement plan |
| [specs/testing.md](specs/testing.md) | Test strategy and coverage gaps |
| [specs/issues.md](specs/issues.md) | Prioritized issue backlog |
| [specs/error-profile.md](specs/error-profile.md) | Production error analysis |
| [specs/data-hypotheses.md](specs/data-hypotheses.md) | Data analysis findings (H1-H7) |

## Invariants

1. Only `status='ok'` memes are served to users
2. Every reaction is persisted even if next_message() fails
3. Double-tap doesn't deliver duplicate memes (reaction_is_new check)
4. Cold start (<30 memes) uses different engine mix than mature users
5. Moderators see low_sent_pool (75%) to review new content
6. All memes must match user's language_code
7. Already-seen memes excluded via LEFT JOIN user_meme_reaction ... IS NULL
