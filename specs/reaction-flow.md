# Reaction Flow (Critical Hot Path)

The most important code path in the system. A bug here breaks the core UX.

## Sequence

```
1. User taps Like/Dislike button
   └─> Telegram sends callback_query to webhook

2. handle_reaction() [src/tgbot/handlers/reaction.py]
   ├─> update_user_info_counters()     — increment cached counters
   ├─> maybe_send_moderator_invite()   — check if user qualifies
   ├─> update_user_last_active_at()    — DB: set last_active
   ├─> update_user_meme_reaction()     — DB: SET reaction_id WHERE reaction_id IS NULL
   │     └─> returns reaction_is_new (bool)
   └─> if reaction_is_new:
         └─> next_message()            — deliver next meme

3. next_message() [src/tgbot/senders/next_message.py]
   ├─> get_user_info()                 — from Redis cache or DB
   ├─> get_next_meme_for_user()        — pop from Redis queue (up to 10 attempts)
   │     ├─> meme_queue.get_next_meme_for_user()  — Redis spop
   │     ├─> user_meme_reaction_exists()           — DB: check already seen
   │     └─> if queue empty: generate_recommendations(limit=7)
   ├─> create_user_meme_reaction()     — DB: INSERT with sent_at (pre-reactive)
   ├─> send meme (edit_last_message or send_new_message)
   ├─> send_popup() if applicable
   └─> check_queue()                   — trigger refill if <= 2 remaining
```

## Race Conditions

**Double-tap**: User taps Like twice fast. Both callbacks arrive. First `update_user_meme_reaction()` succeeds (rowcount=1), second fails (rowcount=0, reaction already set). Handler checks `reaction_is_new` to prevent double next-meme delivery. Works correctly, but generates 391 warnings/day.

**Queue stale entries**: Meme added to queue at time T. User reacts to that meme via another path. Queue still contains stale entry. `get_next_meme_for_user()` pops it, DB check catches it, retries up to 10 times.

## Production Errors (from this path)

- asyncpg contention: 8/day — multiple async ops on same connection
- Telegram timeouts: 5/day — send_video/edit_media fails
- Queue exhaustion: 22 warnings/day — 10 retries all hit already-seen memes

## Files

| File | Functions |
|------|-----------|
| `src/tgbot/handlers/reaction.py` | `handle_reaction()` |
| `src/tgbot/senders/next_message.py` | `next_message()`, `get_next_meme_for_user()` |
| `src/tgbot/senders/meme.py` | `send_new_message_with_meme()`, `edit_last_message_with_meme()` |
| `src/recommendations/service.py` | `update_user_meme_reaction()`, `create_user_meme_reaction()` |
| `src/recommendations/meme_queue.py` | `check_queue()`, `generate_recommendations()` |
| `src/redis.py` | `pop_meme_from_queue_by_key()`, `get_meme_queue_length_by_key()` |

## Test Coverage

**Current: 0%** — No tests cover any function in this path. This is the #1 testing priority.
