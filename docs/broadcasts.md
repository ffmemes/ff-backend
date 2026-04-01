# Broadcasting to Users

Guide for sending bulk messages to bot users. Written after the April 2026 wrapped broadcast incident where users received 3-4 duplicate messages.

## Architecture

- **Engine**: `src/broadcasts/service.py` — `send_broadcast()` function with Redis SET dedup
- **Scripts**: `scripts/broadcast_wrapped.py` — example broadcast script
- **Bot**: uses `src/tgbot/bot.bot` (python-telegram-bot) to send messages
- **Dedup**: Redis SET `broadcast:{id}:sent` tracks which user_ids were already sent to
- **Rate**: configurable delay between sends (default 0.15s = ~7 msg/sec)

## How to Run a Broadcast

### 1. Write the script

Create `scripts/broadcast_<name>.py`. Use `send_broadcast()` from the service layer:

```python
from src.broadcasts.service import get_all_non_blocked_users, send_broadcast

await send_broadcast(
    broadcast_id="my-campaign-2026-04",  # unique, never reuse
    users=await get_all_non_blocked_users(),
    messages={"ru": "...", "en": "..."},
    language_fn=lambda lang: "ru" if lang in ALMOST_CIS_LANGUAGES else "en",
    delay=0.3,
)
```

### 2. Deploy first, then run

Commit, push, merge to production, wait for Coolify deploy to finish. Then run:

```bash
ssh root@65.108.127.32 "docker exec -e PYTHONPATH=/src <container> \
    python scripts/broadcast_<name>.py <broadcast_id> --dry-run"
```

Verify counts in dry run output. Then run without `--dry-run`.

### 3. Monitor

```bash
ssh root@65.108.127.32 "docker exec <container> tail -5 /tmp/broadcast.log"
```

## Rules (Lessons Learned)

### NEVER run a broadcast without dedup

Every broadcast MUST use `send_broadcast()` which checks Redis before each send. The `broadcast_id` is the dedup key. Re-running the same script with the same ID skips already-sent users.

### NEVER run broadcast commands ad-hoc

Do not use `docker exec python -c '...'` with inline code for broadcasts. Do not monkey-patch scripts on the fly. Do not use `sed` to modify scripts in containers. Always use a committed, deployed, tested script with a proper `broadcast_id`.

**Why this matters:** On April 1st 2026, 3 different ad-hoc broadcast attempts ran simultaneously because inline commands were hard to track and verify. Users got 3-4 duplicate messages.

### ONE script, ONE run, ONE broadcast_id

- Write one script
- Deploy it
- Run it once with `--dry-run` to verify
- Run it once for real
- If it crashes, re-run with the SAME `broadcast_id` — dedup handles the rest

### Language detection: use user_language, not user_tg

`user_tg.language_code` is the Telegram app language (phone settings). `user_language` is the bot content preference (what the user chose in the bot). A user can have Telegram in English but prefer Russian memes.

`get_all_non_blocked_users()` already handles this correctly — it checks `user_language` first, falls back to `user_tg.language_code`, then defaults to `'en'`.

### Delay: 0.3s minimum for large broadcasts

- 0.05s (20/sec) — caused DB connection pool exhaustion when combined with /wrapped traffic
- 0.15s (7/sec) — worked but still risky under load
- 0.3s (3/sec) — safe, takes ~70 min for 13K users
- Telegram rate limit: ~30 msg/sec per bot, but the DB pool (size 16, overflow 20) is the real bottleneck

The broadcast script shares the DB connection pool with the main app. Every user who receives the broadcast and clicks /wrapped triggers ~8 concurrent DB queries. At 7 msg/sec, if even 10% of users click immediately, that's dozens of concurrent DB connections on top of the broadcast's own queries.

### Blocked user cleanup

The broadcast script auto-detects users who blocked the bot (Telegram returns "Forbidden: bot was blocked by the user") and marks them as `type='blocked_bot'` in the database. This is a valuable side effect — it cleans up stale users.

### Container replacement kills background processes

Coolify deploys replace containers. Any `docker exec -d` process dies when the old container is removed. The dedup mechanism (`broadcast_id` in Redis) makes this safe — just re-run on the new container.

## Incident: April 1st 2026 Wrapped Broadcast

**What happened:** Users received 3-4 duplicate messages promoting the /wrapped feature.

**Timeline:**
1. Broadcast script written without dedup, deployed
2. Multiple attempts to run it (inline python, sed-modified script, background shell) — 3 ended up executing
3. DB connection pool exhausted (QueuePool 36 connections) from broadcast + /wrapped traffic
4. Broadcast killed, Redis dedup added, re-deployed
5. Redis seeded with RU users only (wrong — should have been ALL users)
6. Resumed broadcast found previously-sent EN users as "unsent" → sent again
7. Language detection used wrong field → Russian users got English messages

**Root causes:**
1. No dedup mechanism from the start
2. Ad-hoc execution (inline python, sed) instead of committed scripts
3. Language detection from `user_tg.language_code` (Telegram app) instead of `user_language` (bot preference)
4. Partial Redis seeding (only RU users, not all)

**Fixes applied:**
- `send_broadcast()` with Redis SET dedup (PR #150)
- Language detection from `user_language` table (PR #151)
- Required `broadcast_id` argument prevents accidental re-runs
- This documentation
