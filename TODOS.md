# TODOS

> Last updated: 2026-03-20. Items marked ~~strikethrough~~ with "DONE" are completed.

## P1 — High Priority

### ~~Create read-only PostgreSQL user for AI agents~~ — DONE
**Context:** Done 2026-03-20. Read-only user created with 30s statement_timeout. ANALYST_DATABASE_URL in .env.

### ~~Remove fast_dopamine_20240804 from blender~~ — DONE
**Context:** Done. Engine removed from all source files.

### ~~Unstarve like_spread_and_recent engine~~ — DONE
**Context:** Done 2026-03-20. Removed `age_days < 30` filter in `src/recommendations/candidates.py`. Candidates 72→thousands. See [specs/experiment-2026-03-20-adaptive-cold-start.md](specs/experiment-2026-03-20-adaptive-cold-start.md).

### Incremental meme_stats computation
**What:** Rewrite `calculate_meme_stats()` to only update memes with reactions in the last 2–3 hours (using `WHERE m.id IN (SELECT DISTINCT meme_id FROM user_meme_reaction WHERE reacted_at > NOW() - INTERVAL '3 hours')`), then upsert only those rows.
**Why:** Full table scan on 22M+ user_meme_reaction rows exceeded 300s Prefect timeout on 2026-03-23 (peak traffic), causing VQ connection storm (22 events) and 6.5h stats staleness. Temporary fix (timeout 300→600s, commit f40b16a) bought headroom but at peak traffic 600s will eventually be insufficient too.
**File:** `src/stats/meme.py` (`calculate_meme_stats()`), `src/flows/stats/meme.py`
**Depends on:** Nothing — isolated change. Verify that meme_stats UPSERT logic handles partial updates correctly (memes with no new reactions keep their existing stats).

### Add per-user recency filter to goat engine
**What:** In the goat SQL query, add a filter to exclude memes the user saw recently (e.g., `sent_at > now() - interval '30 days'` via `user_meme_reaction`). This rotates the GOAT pool per-user.
**Why:** Goat LR declined from 44% → 16% over 6 days post-fix due to pool exhaustion — the same top-ranked GOATs are served repeatedly to users who already saw them. Goat has 98% continuation rate (best engine) so the pool exhaustion is the only issue.
**File:** `src/recommendations/candidates.py` (goat function)
**Depends on:** Nothing — targeted SQL change.

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

## P3 — Nice to Have

### Daily north star log message
**What:** Log line printed hourly: "Session length: median=22, avg=45, WAU=530, share_rate=16.8%".
**Why:** Quick pulse of the product without running queries manually.
**Files:** `src/flows/stats/` (add to existing stats flow)
