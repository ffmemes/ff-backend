# TODOS

> Last updated: 2026-05-12. Items marked ~~strikethrough~~ with "DONE" are completed.

## P1 — High Priority

### ~~Create read-only PostgreSQL user for AI agents~~ — DONE
**Context:** Done 2026-03-20. Read-only user created with 30s statement_timeout. ANALYST_DATABASE_URL in .env.

### ~~Remove fast_dopamine_20240804 from blender~~ — DONE
**Context:** Done. Engine removed from all source files.

### ~~Unstarve like_spread_and_recent engine~~ — DONE
**Context:** Done 2026-03-20. Removed `age_days < 30` filter in `src/recommendations/candidates.py`. Candidates 72→thousands. See [specs/experiment-2026-03-20-adaptive-cold-start.md](specs/experiment-2026-03-20-adaptive-cold-start.md).

### ~~Incremental meme_stats computation~~ — DONE
**Context:** Done 2026-03-27. Rewrote `calculate_meme_stats()` to only update memes with reactions in the last 3 hours, then upsert only those rows. Prevents full-table scan timeout cascade at peak traffic. Commit `84a5119`. See [FFM-5](/FFM/issues/FFM-5).

### ~~Add per-user recency filter to goat engine~~ — DONE
**Context:** Done 2026-04-13. Added per-user recency filter using `reacted_at` in SCORES CTE to exclude memes the user reacted to in the last 30 days. PR #162 + #169, deployed Apr 13. Goat LR recovered to 41.9% (7d) vs 39.4% baseline, continuation 97.5%. Experiment running through Apr 27.

### Auto-discover new TG channels from forwarded messages
**What:** When the TG scraper parses a forwarded post, extract the source channel URL. Store discovered channels in a new `meme_source_candidate` table with status='discovered'. Admin/moderator approval flow to promote to `meme_source`.
**Why:** Meme channels frequently forward from other meme channels. Self-growing pipeline of source candidates.
**Files:** `src/storage/parsers/telegram.py` (extract forwarded_url), `src/database.py` (new table), `alembic/` (migration)
**Depends on:** Nothing technically — design decision on approval UX.

### Auto-snooze broken/dead sources
**What:** If a TG source returns 0 posts for 3 consecutive parse attempts, or its `meme_source_stats` like_rate drops below 10%, auto-set status to 'snoozed' and alert admins via Telegram.
**Why:** Dead/broken sources waste parsing slots. With 108 enabled sources, each dead source delays the cycle for all others.
**Files:** `src/flows/storage/parsers.py` (check after parse), `src/database.py` (meme_source.data JSONB)
**Depends on:** Nothing — small, self-contained change.

## P2 — Medium Priority

### Upgrade pre-commit secrets scanner to detect-secrets
**What:** Replace shell script `.git/hooks/pre-commit` with Yelp's `detect-secrets` framework.
**Why:** Better coverage for public repo, especially when AI agents push code. Current hook has false positives on doc text.
**Depends on:** Phase 2 (Engineer agent pushing code).

### Audit python-telegram-bot 22.7 best practices and handler layout
**What:** Review official PTB 22.7 docs/changelog for handler groups, callback query patterns, lifecycle hooks, rate limiting, webhook/polling setup, and any new recommended syntax. Turn the result into a concrete module layout for `src/tgbot/handlers/`.
**Why:** Source voting and moderator-community features need clearer Telegram handler boundaries without confusing FastAPI routers with Telegram handler registrars.
**Files:** `src/tgbot/app.py`, `src/tgbot/handlers/`, `src/tgbot/handlers/moderator/registry.py`
**Depends on:** Moderator community source-voting prototype design.

### Per-engine session continuation rate
**What:** SQL query that computes, for each engine: % of times user continued scrolling after seeing that engine's meme.
**Why:** Better engine evaluation metric than LR. Directly aligned with session length north star.
**Context:** Measurement SQL already exists in [specs/experiment-2026-03-16-es-ranked.md](specs/experiment-2026-03-16-es-ranked.md) and [specs/experiment-2026-03-20-adaptive-cold-start.md](specs/experiment-2026-03-20-adaptive-cold-start.md).
**Depends on:** Session gap standardization (done: 30 min).

### Incremental engagement_score computation
**What:** Add `WHERE user_id IN (...)` to limit the full-table scan.
**Why:** If the hourly full scan becomes slow as data grows beyond 22M rows.
**Files:** `src/stats/meme.py` (engagement_score calculation)
**Depends on:** V1 engagement_score being deployed.

### Incremental user_stats scan
**What:** Add `WHERE reacted_at > NOW() - INTERVAL '2 days'` to the EVENTS CTE in `calculate_user_stats()`.
**Why:** Full table scan on 22M+ rows. Bounded scan would be faster.
**File:** `src/stats/user.py`
**Depends on:** Nothing — but test session boundary detection still works.

### Add share bonus to engagement_score V2
**What:** Include `invited_count` as a bonus signal in engagement_score.
**Why:** Shares are the highest-intent positive signal.
**File:** `src/stats/meme.py`
**Depends on:** V1 shadow mode validation.

### Skip rate alerting
**What:** Flag memes with >50% skip rate for manual review.
**Why:** These memes are actively boring users.
**File:** `src/stats/meme.py`, `src/flows/stats/meme.py`
**Depends on:** V1 engagement_score validation.

### Cold start quality score
**What:** Compute engagement_score specifically for the first 10 memes each new user sees.
**Why:** 25% of users leave within first 5 memes. See [specs/data-hypotheses.md](specs/data-hypotheses.md) H4.
**Context:** Now measurable via `recommended_by IN ('cold_start_explore', 'cold_start_adapt')` labels.
**Depends on:** Adaptive cold start deployed (DONE).

### ~~Audit all handlers for unhandled Forbidden~~ — DONE
**Context:** Done 2026-03-20. Fixed 4 handlers: `language.py`, `send_tokens.py`, `feedback.py`, `treasury/payments.py`. All now catch `Forbidden` for cross-user message sends. Error handler already protects moderators/admins from demotion.

## Channel Growth

### DRY crossposting scoring functions
**What:** Merge get_next_meme_for_tgchannelru() and get_next_meme_for_tgchannelen() into get_next_meme_for_channel(channel, language_code, weights).
**Why:** 90% identical SQL. When formula changes, need to update in two places. The weights dict becomes the experiment variable for future A/B testing.
**File:** `src/crossposting/service.py`
**Depends on:** Channel growth baseline data (2 weeks after deploy of stats collector)

### Autoresearch loop for channel growth
**What:** AI agent generates scoring formula variants, tags posts with score_version, measures forwards_per_1k_views, keeps winners. Karpathy-inspired automated experimentation.
**Why:** At 6 posts/day, convergence takes weeks manually. Automated loop can test more variants faster.
**Depends on:** 4+ weeks of Telethon stats data + DRY scoring functions

### Fix non-idempotent crossposting flow
**What:** Current flow sends to Telegram BEFORE writing to DB. Failure after send = live post with no DB record (ghost post). Fix: write DB row first with status='pending', send, then update status='sent' + message_id.
**Why:** Stats collector can't match ghost posts. Data loss on retries.
**File:** `src/flows/crossposting/meme.py`
**Depends on:** Nothing

### Channel audience study via giveaway
**What:** Post a deep link button in channel offering +10 burger coins. Track who clicks. Cross-reference with bot users. Use Telethon to analyze their profiles (linked channels, gift exchanges).
**Why:** Understand who reads the channel, what they look like, whether they're already bot users.
**Depends on:** Telethon admin access to channel

### Track channel join/leave events
**What:** Use Telethon admin log to record join/leave events for both channels. Cross-reference with bot user data.
**Why:** Understand churn. Are people who leave the channel still using the bot? Are new joiners converting?
**Depends on:** Telethon admin access to channel

### Backfill historical channel posts to DB
**What:** Bulk-insert the 15K posts from channel_posts_snapshot.json into crossposting_snapshots table after migration.
**Why:** Full historical data for analysis. Currently only new posts (after T2 deploy) will have telegram_message_id.
**File:** channel_posts_snapshot.json -> crossposting_snapshots
**Depends on:** Migration deployed

## P3 — Nice to Have

### Daily north star log message
**What:** Log line printed hourly: "Session length: median=22, avg=45, WAU=530, share_rate=16.8%".
**Why:** Quick pulse of the product without running queries manually.
**Files:** `src/flows/stats/` (add to existing stats flow)
