# Analyst Agent Reference

## Role
The Analyst agent monitors product health, tracks experiments, and produces daily reports for the CEO agent.

## Data Access
- **Database**: Read-only PostgreSQL user (`analyst_readonly`) via `ANALYST_DATABASE_URL` in `.env`
- **Statement timeout**: 30 seconds (kills runaway queries)
- **Future tables**: Automatically accessible (DEFAULT PRIVILEGES granted)

## Key Files
- `docs/analyst/metrics.sql` — SQL queries organized by section (health, north star, engines, retention, etc.)
- `docs/analyst/viral-shares-blender-v1.sql` — readout for `viral_shares_blender_v1` (share clickers + invites vs control + session guardrail).
- `docs/analyst/dwell-feed-vs-broadcast.sql` — `sec_to_react` percentiles: like vs skip × feed vs broadcast; dwell buckets; demote inventory risk.
- `docs/analyst/source-affinity-demote-guardrails.sql` — post-deploy volume / LR checks for soft-demote (#340).
- `docs/analyst/broadcast-reengagement.sql` — retention push HQ vs queue fallback vs feed.
- Living decision calendar: [`experiments/HYPOTHESES.md`](../../experiments/HYPOTHESES.md).
- `docs/growth/2026-08-09-viral-shares-blender-v1.md` — experiment design note (also under `experiments/active/` when tracked).
- `docs/analyst/crossposting.sql` — reusable read-only queries for Telegram channel views/forwards, 24h labels, and pre-posting share signals.
- `specs/crossposting-share-optimization-2026-05-18.md` — current compact crossposting readout and next experiment gate.
- `docs/archive/2026-q2/meme-share-button-readout-2026-06-04.md` — share button canary readout; use non-self `m_`/`s_` deep-link clicks, not raw share clicks.
- `experiments/active/` — Currently running experiments to monitor
- `experiments/completed/` — Historical experiments for context
- `experiments/reports/` — Daily report output
- `experiments/log.jsonl` — Machine-readable audit trail

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
| `message_tg` | All group messages (AI context) | chat_id, message_id, user_id, text, date |

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

For in-bot share-button work, read
`docs/archive/2026-q2/meme-share-button-readout-2026-06-04.md` before interpreting
`user_deep_link_log`: raw `m_`/`s_` counts include self-clicks and should not be
treated as shares.

## Engine Names (recommended_by column)
| Engine | Description | Expected LR |
|--------|-------------|-------------|
| `multiply_all_scores` | Combined scoring | ~47% |
| `like_spread_and_recent_memes` | High-spread viral memes | ~50% |
| `best_memes_from_each_source` | Top meme per source | ~44% |
| `best_memes_from_liked_sources` | User's preferred sources | ~45% |
| `uploaded_memes` | User-uploaded content | ~42% |
| `goat` | Greatest Of All Time | ~43% (after fix) |
| `es_ranked` | Engagement score ranked | TBD |
| `low_sent_pool` | New content (moderators only) | varies |

## Other Data Sources
- **Sentry**: `sentry issue list` — production errors
- **Git log**: `git log --oneline -20` — recent changes
- **TG channel**: @ffmemes — community feedback (read via Bot API)
- **Prefect**: Pipeline health (parser → ETL → final_pipeline)

## North Star Metric
**Session length** (median memes per session). A session starts when a user opens the bot and ends after 30 minutes of inactivity. Higher = better.

Secondary signals: WAU growth, share click rate, D1/D7 retention, cold start like rate.

**Describe Memes throughput**: `described_24h` — memes described by the OpenRouter Vision flow in the last 24h. Expected >0. Zero means the circuit breaker has paused the flow. See "DESCRIBE MEMES THROUGHPUT" section in metrics.sql.

**Chat Agent metrics**: agent_calls_24h, active_chats_24h, avg_response_ms, token_cost_usd, chat meme like rate. See "CHAT AGENT" section in metrics.sql.

See `experiments/README.md` for report format and `docs/analyst/metrics.sql` for the actual queries.
