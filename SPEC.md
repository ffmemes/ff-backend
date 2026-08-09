# SPEC.md

## Product

Telegram meme recommendation bot (@ffmemesbot). Infinite personalized meme feed.
User presses /start → meme with Like/Dislike → reaction triggers next meme.

**Session north star**: session length (memes per session), not like rate alone.  
**Growth north star**: organic users via share deep links — see
[docs/growth/virality-loop.md](docs/growth/virality-loop.md).

**Supply**: ETL of TG channels + VK publics → quality filters → recommendation pool.

## Key Numbers

Historical snapshot (2026-03-13) is intentionally omitted from the living doc —
it goes stale immediately. Prefer the production health SQL in private ops notes
or analyst queries under `docs/analyst/`.

## Critical Flow

```
User taps Like/Dislike
  -> handle_reaction() saves reaction
  -> next_message() pops meme from Redis queue
  -> if queue length <= 8: generate_recommendations via RecommendationBatchPipeline
  -> maturity plan (feed_turn.planner) + SQL engines + blend
  -> meme sent to user (share deep link on keyboard)
```

## Data Flow

```
Sources (TG/VK) -> Parsers (hourly) -> meme_raw_*
  -> ETL (filter, type detect) -> meme (status=created)
  -> Download + Watermark + Upload to TG -> telegram_file_id
  -> Ad filter + Dedup -> status='ok'
  -> Describe Memes (async) -> ocr_result JSONB
  -> Engines -> Blender -> Redis queue -> User
  -> Reactions + share clicks (s_ deep links) -> stats / growth metrics
```

## Detailed Specs

Index: [specs/README.md](specs/README.md)

Living entries (short list):

| File | Scope |
|------|-------|
| [specs/recommendations.md](specs/recommendations.md) | Engines, blender, queue |
| [specs/reaction-flow.md](specs/reaction-flow.md) | Hot path |
| [specs/parsing-etl.md](specs/parsing-etl.md) | ETL (TG/VK) |
| [specs/dedup.md](specs/dedup.md) | Dedup |
| [specs/describe-memes.md](specs/describe-memes.md) | Vision OCR |
| [specs/moderator-community-loop.md](specs/moderator-community-loop.md) | Source voting |
| [docs/growth/virality-loop.md](docs/growth/virality-loop.md) | Growth thesis |

Archived experiments/plans: [specs/archive/](specs/archive/).

## Invariants

1. Only `status='ok'` memes are served to users
2. Every reaction is persisted even if next_message() fails
3. Double-tap doesn't deliver duplicate memes (`reaction_is_new`)
4. Cold start (<30 memes) uses a different engine mix than mature users
5. Moderators get elevated `low_sent_pool` quota to cover new content
6. Memes must match the user's language preferences
7. Already-seen memes excluded via `user_meme_reaction`
8. Prepared sources (`in_moderation`) do not enter the public feed until promoted
