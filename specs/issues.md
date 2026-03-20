# Issues Backlog (Prioritized)

> Last updated: 2026-03-20. Items marked ~~strikethrough~~ are DONE with commit reference.

## Critical (Do First)

### C1: Write tests for reaction hot path
**Why**: 0% coverage on the most important code path. Any change risks breaking production silently.
**Files**: `src/tgbot/handlers/reaction.py`, `src/tgbot/senders/next_message.py`, `src/tgbot/senders/meme.py`, `src/recommendations/service.py`, `src/recommendations/meme_queue.py`
**See**: [testing.md](testing.md) Phase 1

### ~~C2: Kill 3 bad recommendation engines for users~~
**DONE**: goat integer division fixed (commit `67d123f`), less_seen_meme_and_source removed, fast_dopamine removed. goat + es_ranked now at 0.1 weight each. Experiment measuring until 2026-03-21/23. See [experiment-2026-03-14.md](experiment-2026-03-14.md), [experiment-2026-03-16-es-ranked.md](experiment-2026-03-16-es-ranked.md).

### ~~C3: Re-enable Sentry~~
**DONE**: Sentry re-enabled. Forbidden errors filtered from Sentry (commit `e918bec`).

### ~~C4: Fix SQL injection in candidates.py~~
**DONE**: All engines parameterized with `:user_id` bind params (commit `e74ac7a`). `exclude_meme_ids_sql_filter` still uses f-string but only for list of integer IDs from internal code (not user input).

## High (Do Soon)

### H1: Fix asyncpg connection contention
**Why**: ~6 errors/day in Sentry (`InternalClientError: cannot switch to state`). Multiple async ops on same connection.
**File**: `src/database.py`
**Sentry**: FF-BACKEND-V3, FF-BACKEND-V9
**Action**: Review connection pool checkout. Ensure each handler gets its own connection. Consider `pool_size` increase or per-request connection pattern.

### ~~H2: Fix blender random_seed=42~~
**DONE**: Per-user seed with `random.Random(seed)` instance (commit from [experiment-2026-03-14.md](experiment-2026-03-14.md)).

### ~~H3: Switch Redis queue from SET to LIST~~
**DONE**: `rpush/lpop` preserves blender ordering (commit from [experiment-2026-03-14.md](experiment-2026-03-14.md)).

### ~~H4: Increase queue refill threshold~~
**DONE**: Threshold 2→8, batch 5→15 (`src/recommendations/meme_queue.py`). Part of adaptive cold start.

### ~~H5: Optimize cold start with proven retention sources~~
**DONE**: 3-phase adaptive cold start. Phase 1: diverse sources via DISTINCT ON + data-driven source ranking. Phase 2: real-time adaptation from raw reactions. Phase 3: transition to blended engines. See [experiment-2026-03-20-adaptive-cold-start.md](experiment-2026-03-20-adaptive-cold-start.md).
**Files**: `src/recommendations/candidates.py` (cold_start_explore, cold_start_adapt), `src/recommendations/meme_queue.py`

## Medium (Do When Ready)

### ~~M1: Move stats from nightly to hourly~~
**DONE**: Stats run every 15 minutes via Prefect automations. See `scripts/serve_flows.py`.

### M2: Add perceptual image hashing for dedup
**Why**: Cross-source duplicates not detected. 17% dupe rate could decrease further.
**See**: [dedup.md](dedup.md) Stage B
**Files**: `src/database.py` (meme table), `src/storage/etl.py`, `src/flows/storage/memes.py`
**Note**: CLIP-based dedup may not work well for memes (same image + different text). Perceptual hash (imagehash) is more appropriate.

### M3: Reduce log noise
**Why**: 391 "already reacted" warnings/day + 170 "invalid HTTP" warnings mask real errors.
**Files**: `src/recommendations/service.py`, `src/tgbot/handlers/error.py`
**Action**: Downgrade "already reacted" to DEBUG. Rate-limit or ignore scanner HTTP warnings.

### M4: Add retry for Telegram timeouts
**Why**: ~5 timeouts/day (Sentry: FF-BACKEND-VN, FF-BACKEND-VA). User gets stuck with no next meme.
**File**: `src/tgbot/senders/meme.py`
**Action**: Wrap send_video/edit_media in retry with 1-2 attempts, exponential backoff.

### ~~M5: Scale up winning engines~~
**DONE**: like_spread_and_recent unstarved (removed `age_days < 30` filter, candidates 72→thousands). `src/recommendations/candidates.py`. Part of adaptive cold start PR.

### M6: Source quality gating
**Why**: 4x quality variance across sources (18% to 70% LR). No minimum quality floor.
**Files**: `src/recommendations/candidates.py` (all engines)
**Action**: Add minimum LR threshold for sources in recommendation engines. Sources below threshold only served to moderators.

## Low (Nice to Have)

### L1: Automatic source discovery via reposts
**Why**: Telegram forwarded_url data shows which channels sources repost from.
**See**: TODOS.md "Auto-discover new TG channels from forwarded messages"

### L2: Re-engage tryout users (10-29 reactions)
**Why**: Converting tryouts to casuals shows +5pp LR improvement. See [data-hypotheses.md](data-hypotheses.md) H5.
**Action**: Prefect flow sends push notification after 2-day absence for users with 10-29 reactions.

### L3: Time-aware quality thresholds
**Why**: 13pp LR swing between morning (49%) and night (36%). See [data-hypotheses.md](data-hypotheses.md) H7.
**Action**: Serve higher-LR-threshold memes during UTC 20-23.

### L4: Engine auto-throttling
**Why**: No automatic feedback loop. Bad engines keep traffic until manually adjusted.
**Action**: If engine's 7-day LR drops below floor (35%) at significant traffic, auto-reduce weight.
**Files**: `src/recommendations/meme_queue.py` (engine weights)

### L5: Per-engine live metrics dashboard
**Why**: No real-time visibility into engine performance.
**Action**: Log per-engine impressions/likes/dislikes. Measurement SQL exists in experiment specs.
**See**: [experiment-2026-03-14.md](experiment-2026-03-14.md), [experiment-2026-03-16-es-ranked.md](experiment-2026-03-16-es-ranked.md), [experiment-2026-03-20-adaptive-cold-start.md](experiment-2026-03-20-adaptive-cold-start.md)
