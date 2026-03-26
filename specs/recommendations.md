# Recommendation System

## Architecture

```
User reacts -> handle_reaction() -> update_user_meme_reaction()
    -> next_message() -> pop from Redis queue
    -> if queue low (<= 2) -> generate_recommendations(limit=5)
    -> select engines by user maturity -> asyncio.gather()
    -> blend() -> push to Redis SET (TTL 1h)
```

Key files:
- `src/recommendations/candidates.py` — 9 SQL engines + CandidatesRetriever
- `src/recommendations/blender.py` — weighted random sampling
- `src/recommendations/meme_queue.py` — queue check/refill/maturity routing
- `src/recommendations/service.py` — reaction persistence, reaction_exists check

## Engine Performance (Production Data)

| Engine | Traffic % | Like Rate % | Verdict |
|--------|--------:|----------:|---------|
| lr_smoothed | 41.4 | 46.6 | Workhorse, keep |
| best_uploaded_memes | 11.8 | 46.4 | Good, keep |
| recently_liked | 9.6 | 42.7 | Underperforms, investigate |
| classic | 8.8 | 46.8 | Solid, keep |
| **low_sent_pool** | **6.6** | **27.4** | **REMOVE from users** |
| like_spread_and_recent | 6.1 | 50.4 | Best quality, scale up |
| **goat** | **4.0** | **20.0** | **REMOVE from users** |
| **less_seen_meme_and_source** | **3.2** | **30.9** | **REMOVE from users** |
| multiply_all_scores | 1.5 | 46.9 | Good, scale up |
| selected_sources_240513 | 0.3 | 51.3 | Promising, test at scale |

3 bad engines = 13.8% of traffic at sub-31% LR. Removing them is the #1 quick win.

## User Maturity Stages

| Stage | Trigger | Engines | Weights |
|-------|---------|---------|---------|
| Cold start | nmemes_sent < 30 | best_uploaded_memes, fast_dopamine | Sequential fallback |
| Growing | 30-100 | best_uploaded_memes, fast_dopamine, lr_smoothed, recently_liked, goat | 0.1, 0.2, 0.2, 0.2, 0.2 |
| Mature | 100+ | best_uploaded_memes, like_spread_and_recent, lr_smoothed, recently_liked, goat | 0.3, 0.3, 0.4, 0.2, 0.2 |
| Moderator/Admin | user_type check | 75% low_sent_pool + 25% regular | By maturity |

Note: `fixed_pos={0: "lr_smoothed"}` forces first position to lr_smoothed in blended mode.

## Known Bugs

### 1. SQL Injection (HIGH)
All engines use f-string interpolation: `f"... user_id = {user_id} ..."`. Must parameterize.

### 2. Hardcoded random_seed=42 (MEDIUM)
`blender.py` line 30: `random.seed(random_seed)` with default 42. Same ordering for all users. Fix: per-user seed from `hash((user_id, queue_refill_count))`.

### 3. Redis SET loses blending order (MEDIUM)
Queue uses Redis SET (`spop` = random). Blender carefully orders memes, then SET randomizes them. Should use LIST with `rpush/lpop`.

### 4. Queue threshold too low (MEDIUM)
Refill triggers at `queue_length <= 2` with batch size 5. Fast users exhaust queue before refill completes. Increase to 8-10.

### 5. Post-pop dedup is wasteful (LOW)
`next_message.py` pops meme from queue, then checks DB if user already reacted. Up to 10 DB queries per meme delivery. Should filter at enqueue time.

### 6. Dead code: generate_cold_start_recommendations()
`meme_queue.py` lines 51-74 — function exists but is never called. `generate_recommendations()` has its own cold-start path.

## Personalization Quality Assessment

Current personalization uses:
- `user_language` (language match filter)
- `user_meme_source_stats` (per-user source affinity = user-source like rate)
- `meme_stats.lr_smoothed` (global smoothed like rate)

This is better than random but shallow:
- No fine-grained meme-level personalization (e.g., topic, humor style)
- Source affinity is the strongest signal — users who like memes from a source get more from that source
- No exploration budget — all engines optimize exploitation
- No collaborative filtering (users who liked X also liked Y)
