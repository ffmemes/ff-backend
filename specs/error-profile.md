# Error Profile

> Source: Coolify logs, 2026-03-12 to 2026-03-13
> Sentry is DISABLED (commented out in src/main.py)

## Errors (ERROR level)

| # | Error | Count/day | Impact |
|---|-------|-----------|--------|
| 1 | asyncpg InternalClientError: another operation in progress | 8 | Breaks reaction + recommendation flow |
| 2 | telegram.error.TimedOut | 5 | User gets no next meme |
| 3 | telegram.error.Forbidden: bot blocked | 1 | Messaging blocked user during onboarding |
| 4 | UserNotFound in upload handler | 1 | Upload crashes for unknown user |
| 5 | Error handler itself fails | 1 | Error reporting is broken |

## Warnings (WARNING level)

| # | Warning | Count/day | Impact |
|---|---------|-----------|--------|
| 1 | User already reacted to meme | 391 | Log noise, not a bug (double-tap race) |
| 2 | Invalid HTTP request | 170 | External scanners, not actionable |
| 3 | Failed to find unseen meme after 10 attempts | 22 | User stuck, queue exhaustion |

## Root Causes

1. **asyncpg contention**: Multiple async DB operations share a connection in the reaction handler chain. Needs connection pool checkout review in `src/database.py`.

2. **Telegram timeouts**: Large video files + Telegram rate limiting. No retry mechanism.

3. **Queue exhaustion**: Memes enter Redis queue but user reacts before queue refreshes. Post-pop DB check catches stale entries but wastes attempts.

4. **Log noise**: "Already reacted" is the most common log event (391/day). Should be DEBUG, not WARNING.
