# Analytics Reference

## Purpose
These queries and reports support product-health monitoring and experiment analysis.

## Data Access
- **Database**: Read-only PostgreSQL user (`analyst_readonly`) via `ANALYST_DATABASE_URL` in `.env`
- **Statement timeout**: 30 seconds (kills runaway queries)
- **Future tables**: Automatically accessible (DEFAULT PRIVILEGES granted)

## Key Files
- `docs/analyst/metrics.sql` — SQL queries organized by section (health, north star, engines, retention, etc.)
- `docs/analyst/command-surface-proxies.sql` — private slash commands from `message_tg` (`chat_id > 0`) + secondary feature proxies. Notes: [`docs/product/surface-and-commands.md`](../product/surface-and-commands.md).
- `docs/analyst/describe-memes-health.sql` + [readout 2026-08-13](readouts/2026-08-13-describe-memes-health.md) — OCR / OpenRouter describe throughput vs 864/day target; backlog ~222k.
- `docs/analyst/phash-shadow.sql` — dHash (`meme.image_hash`) shadow dedup: coverage, exact-hash collision groups by type, agreement with `duplicate_of`, sample pairs for precision checks. Backfill: `scripts/admin/backfill_image_hash.py`.
- Meme inspect API (JSON + media download via bot token): [`docs/admin-meme-inspect.md`](../admin-meme-inspect.md).
- `docs/analyst/dwell-feed-vs-broadcast.sql` — `sec_to_react` percentiles: like vs skip × feed vs broadcast; dwell buckets; demote inventory risk.
- `docs/analyst/source-affinity-demote-guardrails.sql` — post-deploy volume / LR checks for soft-demote (#340).
- `docs/analyst/broadcast-reengagement.sql` — retention push HQ vs queue fallback vs feed.
- Living decision calendar (which experiments are live and which SQL each uses): [`docs/growth/HYPOTHESES.md`](../growth/HYPOTHESES.md). SQL for killed experiments is deleted; recover it from version control history if needed.
- `docs/analyst/crossposting.sql` — reusable read-only queries for Telegram channel views/forwards, 24h labels, and pre-posting share signals.
- `specs/crossposting-share-optimization-2026-05-18.md` — current compact crossposting readout and next experiment gate.
- `experiments/active/` — Currently running experiments to monitor
- `experiments/completed/` — Historical experiments for context

## Database Schema Reference
Full table definitions: `src/database.py`

Key tables for analytics:
| Table | What It Holds | Key Columns |
|-------|---------------|-------------|
| `user_meme_reaction` | Every like/dislike (22M+ rows) | user_id, meme_id, recommended_by, sent_at, reaction_id, reacted_at |
| `meme_stats` | Aggregated meme metrics (updated every 15 min) | lr_smoothed, nlikes, ndislikes, nmemes_sent, engagement_score, invited_count |
| `user_stats` | User engagement metrics | nlikes, ndislikes, nsessions, median_session_length, time_spent_sec |
| `meme_source_stats` | Source quality metrics | nlikes, ndislikes, nmemes_sent, nmemes_parsed |
| `user_meme_source_stats` | Per-user per-source affinity | nlikes, ndislikes |
| `meme` | All memes (535K total, 205K with status='ok') | status, type, telegram_file_id, language_code, meme_source_id |
| `meme_source` | Content sources (TG/VK/IG channels) | url, status, language_code, type |
| `user_deep_link_log` | Share click tracking (growth proxy) | user_id, deep_link, created_at |
| `chat_agent_usage` | AI agent calls in group chats | chat_id, user_id, prompt_tokens, completion_tokens, tool_calls, response_time_ms, trigger_type |
| `chat_meme_reaction` | Like/dislike votes on memes in group chats | chat_id, meme_id, user_id, reaction (1=like, 2=dislike) |
| `message_tg` | Group messages (AI context) **and private inbound DMs** (commands/text/media) | chat_id (>0 private), message_id, user_id, text, date |

## Reaction ID Mapping
- `reaction_id = 1` → Like (👍)
- `reaction_id = 2` → Dislike (⬇️ "next meme", NOT explicit dislike)
- `reaction_id IS NULL` → Sent but no reaction yet (skip/abandon)

**Critical context**: Dislike = "next meme" skip, not negative signal. Fast dislikes (<2s) on text memes = "didn't bother reading", not "bad content."

## Share Attribution

Telegram bot shares and Telegram channel shares are different signals:

- In-bot share clicks use `m_{sharer_user_id}_{meme_id}` in `user_deep_link_log`;
  legacy rows may still use `s_{sharer_user_id}_{meme_id}`.
- Channel post deep links use `sc_{meme_id}_{channel}` in `user_deep_link_log`.
- Telegram channel forwards/views live in `crossposting` and `crossposting_snapshots`, collected by Telethon.

For channel-growth work, read `docs/analyst/crossposting.sql` and
`specs/crossposting-share-optimization-2026-05-18.md` before writing new SQL.

For in-bot share-button work, when interpreting `user_deep_link_log`: raw `m_`/`s_` counts include self-clicks and should not be
treated as shares; count non-self clicks only.

## Engine Names (recommended_by column)
No hardcoded engine list or expected LRs here; they drift. Sources of truth:
- Feed engines: `CandidatesRetriever.engine_map` in `src/recommendations/candidates.py`.
- Blend weights per maturity stage: `GROWING_BLEND_WEIGHTS` / `MATURE_BLEND_WEIGHTS` in `src/feed_turn/planner.py`.
- Other labels: `low_sent_pool` (moderators), `cold_start_*`, `broadcast_*` (retention pushes; keep them out of feed dwell/LR analysis, see `broadcast-reengagement.sql`).
- Old rows still carry removed engines (e.g. `multiply_all_scores`, `best_memes_from_each_source`); they are no longer served.

## Other Data Sources
- **Sentry**: `sentry issue list` — production errors
- **Git log**: `git log --oneline -20` — recent changes
- **TG channel**: @ffmemes — community feedback (read via Bot API)
- **Prefect**: Pipeline health (parser → ETL → final_pipeline)

## North Star Metric
Defined once in [`SPEC.md`](../../SPEC.md) (session length + organic growth via shares). The experiment ship bar (funnel + k-factor, with session length and block rate as guardrails) is in [`docs/growth/HYPOTHESES.md`](../growth/HYPOTHESES.md). Do not restate either here.

Operational health signals:

**Describe Memes throughput**: `described_24h` — memes described by the OpenRouter Vision flow in the last 24h. Expected >0. Zero means the circuit breaker has paused the flow. See "DESCRIBE MEMES THROUGHPUT" section in metrics.sql.

**Chat Agent metrics**: agent_calls_24h, active_chats_24h, avg_response_ms, token_cost_usd, chat meme like rate. See "CHAT AGENT" section in metrics.sql.

See `experiments/README.md` for report format and `docs/analyst/metrics.sql` for the actual queries.
