# Moderator Community Loop

Date: 2026-05-12
Status: draft

## Goal

Turn the existing moderator chat into a lightweight source-scouting loop.

The first feature is not general moderation. It is source voting:

1. The bot posts a discovered Telegram source candidate into the moderator chat.
2. Chat members vote whether this source deserves trial parsing.
3. Each Telegram user has one current vote per source poll.
4. A user can change their vote; counters update from unique voters.
5. After the voting window closes, passing sources enter a controlled trial.

This runs in `TELEGRAM_MODERATOR_CHAT_ID`, not the uploaded-meme review chat.

## Existing Pieces

- `meme_source_candidate`: queue of TG channels discovered from forwarded posts.
- `/discoveredsources`: private moderator command listing pending candidates.
- `promote_source_candidate()`: promotes a candidate into `meme_source`.
- `advance_meme_source()`: shared source transition logic with audit trail.
- `chat_meme_reaction`: existing "one chat user = one mutable vote" pattern for group meme reactions.
- `src.tgbot.handlers.moderator.registry.add_moderator_handlers()`: the Telegram handler registrar for moderator-facing bot behavior.

Do not create a generic moderation framework. Keep this feature narrow.

## Handler Boundary

New moderator-community handlers should be registered from `add_moderator_handlers()`, not directly in `src/tgbot/app.py`.

Use "handler registrar" for python-telegram-bot registration code. Do not call this a router in this repo: `src/tgbot/router.py` is the FastAPI webhook router, which is a different concept.

The existing `src/tgbot/app.py` remains the composition root: it builds the application and calls feature registrars in order. Feature modules own their own Telegram handlers.

Moderator-adjacent upload behavior should stay split:

- user-facing meme upload stays in `src/tgbot/handlers/upload`;
- upload approval/rejection stays tied to the **Upload Review Chat**;
- source voting and moderator-community source scouting stay under `src/tgbot/handlers/moderator`.

## Data Model

Add two tables.

### `meme_source_candidate_poll`

One row per moderator-chat voting message.

Fields:

- `id integer primary key`
- `candidate_id integer not null references meme_source_candidate(id) on delete cascade`
- `chat_id bigint not null`
- `message_id bigint null`
- `status string not null default 'draft'`
- `opened_at timestamp null`
- `closes_at timestamp not null`
- `closed_at timestamp null`
- `result_meme_source_id integer null references meme_source(id) on delete set null`
- `data jsonb null`
- `created_at timestamp not null default now()`
- `updated_at timestamp null`

Statuses:

- `draft`: DB row exists, Telegram message not posted yet.
- `open`: buttons are live.
- `passed`: vote passed and candidate was promoted.
- `rejected`: vote failed and candidate was dismissed.
- `expired_no_quorum`: not enough unique voters; candidate can be retried later.
- `cancelled`: bot/admin cancelled the poll.

Indexes:

- `(status, closes_at)` for the finalizer.
- `candidate_id` for lookup/history.
- unique `(chat_id, message_id)` where `message_id IS NOT NULL`.
- partial unique open poll per candidate:
  `UNIQUE (candidate_id) WHERE status IN ('draft', 'open')`.

Why a poll table exists:

- Need `poll_id` before posting so callback data can be short: `mscv:{poll_id}:1`.
- Need to track chat message, close time, status, and final trial result.
- Avoid hiding lifecycle state in `meme_source_candidate.data`.

### `meme_source_candidate_vote`

One row per user per poll. This is the source of truth for unique counters.

Fields:

- `poll_id integer not null references meme_source_candidate_poll(id) on delete cascade`
- `user_id bigint not null`
- `vote smallint not null`
- `created_at timestamp not null default now()`
- `updated_at timestamp null`
- primary key `(poll_id, user_id)`

Vote values:

- `1`: add trial
- `2`: skip

Do not foreign-key `user_id` to `user.id`. The authority here is "pressed a button inside the moderator chat", and some legacy/manual chat members may not have a clean current `user` row. This matches the existing `chat_meme_reaction.user_id` pattern.

Do not store yes/no counters as source-of-truth columns. They are derived:

```sql
SELECT vote, count(*) AS voters
FROM meme_source_candidate_vote
WHERE poll_id = :poll_id
GROUP BY vote;
```

This avoids race bugs when a user switches from yes to no.

## Callback Contract

Callback data:

```text
mscv:{poll_id}:{vote}
```

Examples:

- `mscv:123:1` means add trial.
- `mscv:123:2` means skip.

Button labels:

- `✅ Add trial 4`
- `❌ Skip 1`

The callback handler must:

1. Load the poll.
2. Ensure `poll.status = 'open'`.
3. Ensure `now() < poll.closes_at`.
4. Ensure `update.effective_chat.id = TELEGRAM_MODERATOR_CHAT_ID`.
5. Ensure callback `chat_id` matches `poll.chat_id`.
6. Upsert the vote:

```sql
INSERT INTO meme_source_candidate_vote (poll_id, user_id, vote)
VALUES (:poll_id, :user_id, :vote)
ON CONFLICT (poll_id, user_id)
DO UPDATE SET vote = EXCLUDED.vote, updated_at = now();
```

7. Recompute unique counts from `meme_source_candidate_vote`.
8. Edit only the reply markup with refreshed counters.
9. Answer callback with a short message: `Голос учтен` or `Голос изменен`.

If the poll is closed, answer `Голосование уже закрыто` and do not write.

## Poll Posting Flow

Run from a small scheduled flow or admin command.

1. Select candidates:
   - `meme_source_candidate.status = 'discovered'`;
   - no `draft/open` poll exists for the candidate;
   - no poll was posted for the candidate in the last 7 days;
   - URL does not already exist in `meme_source`;
   - order by `times_forwarded DESC, last_seen_at DESC`.
2. Insert `meme_source_candidate_poll` as `draft`, with `closes_at = now() + interval '24 hours'`.
3. Send Telegram message to `TELEGRAM_MODERATOR_CHAT_ID` with callback buttons containing the new `poll_id`.
4. Update poll with `chat_id`, `message_id`, `opened_at`, `status='open'`.
5. If send fails, mark `status='cancelled'` and keep the candidate discoverable.

Start with 1-3 source polls per day to avoid turning the chat into an ops feed.

Message content should include:

- source URL;
- `times_forwarded`;
- when first/last seen;
- sample source language if known;
- one-line explanation: "Vote means: give this source trial parsing, not permanent approval."

## Closing Rule

First prototype:

- voting window: 24 hours;
- quorum: 5 unique voters;
- pass threshold: yes share >= 70%;
- admin veto can be added later, but do not block v1 on it.

Outcomes:

- `total < 5`: mark poll `expired_no_quorum`; candidate remains `discovered` but is not reposted for 7 days.
- `yes / total >= 0.70`: mark poll `passed`; promote and trial-enable the source.
- otherwise: mark poll `rejected`; dismiss candidate with `dismissed_reason='source_vote:{poll_id}'`.

Do not early-close as soon as five yes votes appear. The first experiment should measure participation across a full day.

## Passing Source Flow

On pass:

1. Call `promote_source_candidate(candidate_id, added_by_user_id=<system/admin id>)`.
2. Determine language:
   - preferred: inherit `language_code` from `sample_meme_source_id`;
   - fallback: leave in `in_moderation` and ask an admin/moderator to choose language.
3. If language is known, call `advance_meme_source()`:
   - `moderator_id='source-vote:{poll_id}'`
   - `language_code=<inherited language>`
   - `status='parsing_enabled'`
   - `trigger_parse=True`
4. Merge vote/trial metadata into `meme_source.data`:

```json
{
  "source_vote": {
    "poll_id": 123,
    "candidate_id": 90,
    "chat_id": -1001305866294,
    "message_id": 456,
    "yes": 7,
    "no": 1,
    "closed_at": "2026-05-12T20:00:00Z"
  },
  "trial": {
    "status": "active",
    "started_at": "2026-05-12T20:00:00Z",
    "target_regular_impressions": 300,
    "min_ok_memes": 20
  }
}
```

5. Update poll `result_meme_source_id`.
6. Edit the moderator-chat message with final result.

## Trial Measurement

The vote decides whether to test. It does not decide permanent quality.

Evaluate a trial source using regular-user outcomes:

- exclude `user.type IN ('moderator', 'admin')`;
- minimum sample: 20 ok memes or 300 regular-user impressions;
- primary metric: source-level regular-user `engagement_score` / `lr_smoothed`;
- secondary: regular like rate, fast-skip rate, median `sec_to_react`, duplicate/ad rate;
- compare against sources with the same language and similar recency.

Decision:

- above median comparable source: keep `parsing_enabled`;
- below p25 comparable source after sample: `snoozed`;
- no sample yet: keep trial active.

## Why This Shape

This avoids table sprawl:

- `meme_source_candidate` remains discovery queue.
- `meme_source_candidate_poll` is the chat decision lifecycle.
- `meme_source_candidate_vote` is the one-user-one-current-vote ledger.
- `meme_source.data` stores trial metadata after promotion.

It also avoids counter bugs:

- no duplicate votes because `(poll_id, user_id)` is the key;
- repeated same vote only updates `updated_at`;
- switching yes to no changes exactly one row;
- displayed counters are always derived from unique vote rows.

## Prototype Scope

Ship the smallest useful version:

1. Migration + `database.py` table definitions.
2. Poll posting service for one candidate.
3. Callback handler with mutable unique votes.
4. Manual/admin command or small scheduled flow to post 1 source poll.
5. Finalizer for closed polls.
6. Basic tests:
   - repeated same vote does not increase count;
   - yes -> no changes counts;
   - non-moderator-chat callback is rejected;
   - expired poll rejects new votes;
   - passed poll promotes candidate once.

Do not build weighted scout scores in v1. Record clean votes first; weighting can come after we have data.
