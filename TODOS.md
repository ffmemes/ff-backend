# TODOS

## P1 — High Priority

### Remove bad engines from user traffic
**What:** Remove `goat`, `less_seen_meme_and_source` from regular user blender weights. Keep `low_sent_pool` for moderators only.
**Why:** These engines have 6-31% like rate vs 47% for top engines. 14% of traffic serves bad memes.
**Context:** Goat integer division fix deployed 2026-03-14. Early signal (2 days): goat LR went from 6.6% to 43.1% — the fix worked. Wait for full 7-day measurement on 2026-03-21 before deciding whether to keep or remove goat. Dead engines already removed (less_seen_meme_and_source, fast_dopamine, etc.). See `specs/experiment-2026-03-14.md`.
**Depends on:** Experiment results from 2026-03-21.

### Unstarve like_spread_and_recent engine
**What:** Relax filters on `like_spread_and_recent_memes` engine — remove `age_days < 30` constraint.
**Why:** Best engine (50.7% LR) has only 72 candidates due to restrictive filters. Serves only 1% of traffic despite 0.3 blender weight. H3 proved freshness doesn't correlate with quality.
**Context:** The `raw_impr_rank = 0` filter already limits to top-quartile viral memes. `age_days < 30` is redundant and starves the engine.
**Depends on:** Nothing — quick fix.

### Auto-discover new TG channels from forwarded messages
**What:** When the TG scraper parses a forwarded post, extract the source channel URL. Store discovered channels in a new `meme_source_candidate` table with status='discovered'. Admin/moderator approval flow to promote to `meme_source`.
**Why:** Meme channels frequently forward from other meme channels. This creates a self-growing pipeline of source candidates without manual discovery. Currently all sources are added manually.
**Context:** The scraper already extracts `forwarded_url` per post. Needs: (1) new DB table + migration, (2) dedup logic (don't re-discover known sources), (3) approval UX — could start admin-only, later add moderator voting with time-gated polls. Quality filtering TBD: some forwarded channels may not be meme channels.
**Depends on:** Nothing technically — design decision on approval UX.

### Auto-snooze broken/dead sources
**What:** If a TG source returns 0 posts for 3 consecutive parse attempts, or its `meme_source_stats` like_rate drops below 10%, auto-set status to 'snoozed' and alert admins via Telegram.
**Why:** Dead/broken sources waste parsing slots (currently 25/hour). With 108 enabled sources, each dead source delays the cycle for all others.
**Context:** Need a `consecutive_empty_parses` counter (could be stored in `meme_source.data` JSONB). The watchdog or the parser flow itself can check and snooze. Admin alert allows manual review before permanent disable.
**Depends on:** Nothing — small, self-contained change.

## P2 — Medium Priority

### Per-engine session continuation rate
**What:** SQL query that computes, for each engine: % of times user continued scrolling after seeing a meme from that engine.
**Why:** Replaces per-engine like rate as the engine evaluation metric. Directly aligned with session length north star.
**Context:** Can start with ad-hoc SQL queries. Later, add to a Prefect monitoring flow.
**Depends on:** Session gap standardization (done: 30 min).

### Incremental engagement_score computation
**What:** Add `WHERE user_id IN (SELECT DISTINCT user_id FROM user_meme_reaction WHERE sent_at > NOW() - INTERVAL '2 hours')` to limit the full-table scan.
**Why:** If the hourly full scan becomes slow as data grows beyond 22M rows.
**Context:** V1 uses full scan (same approach as lr_smoothed). Monitor query time during shadow mode. If >30s, add this.
**Depends on:** V1 engagement_score being deployed.

### Add share bonus to engagement_score V2
**What:** Include `invited_count` as a bonus signal in engagement_score (e.g. flat +0.3 if shared).
**Why:** Shares are the highest-intent positive signal but were dropped from V1 because the per-reaction weight (+3.0) doesn't map cleanly to the per-meme `invited_count`.
**Context:** Engines can already boost by `invited_count` independently via `ORDER BY engagement_score * CASE WHEN MS.invited_count > 0 THEN 1.3 ELSE 1 END`.
**Depends on:** V1 shadow mode validation.

### Skip rate alerting
**What:** Flag memes with >50% skip rate (sent but unreacted while user continues) for manual review.
**Why:** These memes are actively boring users — auto-demoting or flagging them improves feed quality.
**Context:** Depends on skip detection being validated in engagement_score V1.
**Depends on:** V1 engagement_score validation.

### Cold start quality score
**What:** Compute engagement_score specifically for the first 10 memes each new user sees.
**Why:** 25% of users leave within first 5 memes (H4). This metric tells you if cold start is hooking users.
**Context:** See `specs/data-hypotheses.md` H4.
**Depends on:** V1 engagement_score validation.

### Audit all handlers for unhandled Forbidden that could demote privileged users
**What:** Review all handlers that send messages to users (forward_channel.py, waitlist.py, explain_meme.py, etc.) and ensure `Forbidden` exceptions are caught at the call site, not left to bubble to the global error handler.
**Why:** The same bug that demoted @rinreiss (moderator → blocked_bot) can happen in any handler that sends a message to a different user than `effective_user`. The error handler now protects moderators/admins, but the unhandled Forbidden is still messy (logs a false "blocked the bot" warning for regular users in some cases).
**Context:** Fixed the critical path in moderation.py (2026-03-19). Error handler now skips demotion for privileged users. But other handlers still let Forbidden bubble up. Low urgency since the error handler protection is in place.
**Depends on:** Nothing.

## P3 — Nice to Have

### Daily north star log message
**What:** Log line printed hourly: "Session length: median=22, avg=45, WAU=530, share_rate=16.8%".
**Why:** Quick pulse of the product without running queries manually.
**Context:** Could be a simple Prefect flow or a log statement in the existing stats flow.
