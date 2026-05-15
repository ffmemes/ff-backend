# Recommendation System

## Architecture

```
User reacts -> handle_reaction() -> update_user_meme_reaction()
    -> next_message() -> pop from Redis queue
    -> if queue low (<= 8) -> generate_recommendations(limit=15)
    -> select engines by user maturity -> asyncio.gather()
    -> blend() -> push to Redis LIST (TTL 1h)
```

Key files:
- [`src/recommendations/candidates.py`](../src/recommendations/candidates.py) — SQL engines + CandidatesRetriever
- [`src/recommendations/blender.py`](../src/recommendations/blender.py) — weighted random sampling
- [`src/recommendations/meme_queue.py`](../src/recommendations/meme_queue.py) — queue check/refill/maturity routing
- [`src/recommendations/service.py`](../src/recommendations/service.py) — reaction persistence, reaction_exists check

## Engines (current, as of `candidates.py` engine_map)

| Engine | What it does |
|--------|-------------|
| `best_uploaded_memes` | Top user-uploaded memes by like rate |
| `lr_smoothed` | Global smoothed like rate ranking |
| `text_light_lr_smoothed` | Same as `lr_smoothed`, but excludes OCR text above 30 words |
| `like_spread_and_recent_memes` | High like rate + recent + reach diversity |
| `recently_liked` | Memes from sources the user recently liked |
| `goat` | All-time best memes by like rate (see [TODOS.md](../TODOS.md) for per-user recency filter) |
| `es_ranked` | Ranked by engagement_score (time-weighted, accounts for skips). See [experiment](experiment-2026-03-16-es-ranked.md) |
| `cold_start_explore` | Broad exploration for new users (<30 memes) |
| `cold_start_adapt` | Adapts to early reactions. See [experiment](experiment-2026-03-20-adaptive-cold-start.md) |

Removed engines: `fast_dopamine`, `classic`, `multiply_all_scores`, `selected_sources_240513`, `less_seen_meme_and_source`, `low_sent_pool` (for non-moderators). See [experiment-2026-03-14.md](experiment-2026-03-14.md).

## User Maturity Stages

| Stage | Trigger | Engines | Source |
|-------|---------|---------|--------|
| Cold start | nmemes_sent < 30 | 3-phase adaptive with text-light guards: explore/adapt/fallback avoid OCR text above 30 words | [`meme_queue.py`](../src/recommendations/meme_queue.py) |
| Growing | 30-100 | A/B: control uses `lr_smoothed`; treatment swaps that slot to `text_light_lr_smoothed` | [`meme_queue.py`](../src/recommendations/meme_queue.py) |
| Mature | 100+ | Recently-liked blender v2, then A/B text-light overlay can swap `lr_smoothed` to `text_light_lr_smoothed` | [`meme_queue.py`](../src/recommendations/meme_queue.py) |
| Moderator/Admin | user_type check | 75% low_sent_pool + 25% regular (by maturity) | [`meme_queue.py`](../src/recommendations/meme_queue.py) |

`fixed_pos={0: "lr_smoothed"}` forces first position to `lr_smoothed` in blended mode. In the `text_light_blender_v1` treatment, that fixed slot becomes `text_light_lr_smoothed`.

## Known Bugs

### 1. SQL Injection (HIGH)
All engines use f-string interpolation: `f"... user_id = {user_id} ..."`. Must parameterize. See [issues.md](issues.md).

### 2. Dead code: generate_cold_start_recommendations()
`meme_queue.py` — function exists but is never called. `generate_recommendations()` has its own cold-start path.

### 3. Post-pop dedup is wasteful (LOW)
`next_message.py` pops meme from queue, then checks DB if user already reacted. Up to 10 DB queries per meme delivery. Should filter at enqueue time.

Resolved bugs (kept for history): random_seed=42 (fixed: per-user seed), Redis SET loses order (fixed: uses LIST now), queue threshold too low (fixed: threshold=8, batch=15).

## Personalization Quality

Current signals:
- `user_language` (language match filter)
- `user_meme_source_stats` (per-user source affinity = user-source like rate)
- `meme_stats.lr_smoothed` (global smoothed like rate)

Gaps:
- No fine-grained meme-level personalization (topic, humor style)
- No exploration budget (all engines optimize exploitation)
- No collaborative filtering (users who liked X also liked Y)

## Related Specs
- [experiment-2026-03-14.md](experiment-2026-03-14.md) — removed bad engines, queue threshold fix
- [experiment-2026-03-16-es-ranked.md](experiment-2026-03-16-es-ranked.md) — engagement_score engine
- [experiment-2026-03-20-adaptive-cold-start.md](experiment-2026-03-20-adaptive-cold-start.md) — 3-phase cold start
- [channel-growth-optimization.md](channel-growth-optimization.md) — crossposting scoring (separate from bot recommendations)
