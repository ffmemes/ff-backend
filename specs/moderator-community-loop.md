# Moderator Community Loop

Date: 2026-05-12
Status: draft

## Goal

Turn the existing moderator chat into a lightweight source-scouting loop.

The first feature is not general moderation. It is source voting:

Once per day, the bot advances a simple moderator-chat ritual:

1. Post the 24-hour report for the previously added source, if one exists.
2. Close the currently open source poll, if one exists.
3. If the poll passed, enable the prepared source.
4. Prepare at most one new Russian-language Telegram source candidate and post it with like/dislike buttons, if one exists.

Each Telegram user has one current vote per source poll and can change it while the poll is open.

This runs in `TELEGRAM_MODERATOR_CHAT_ID`, not the uploaded-meme review chat.

## Existing Pieces

- `meme_source_candidate`: queue of TG channels discovered from forwarded posts.
- `/discoveredsources`: private moderator command listing pending candidates.
- `promote_source_candidate()`: currently creates a `meme_source` row with `status='in_moderation'`. The daily source cycle should split this into "prepare source" and "enable source" behavior so the source can cache raw posts before the vote without entering recommendations.
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
- `prepared_meme_source_id integer null references meme_source(id) on delete set null`
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
- `passed`: vote passed and the prepared source was enabled.
- `rejected`: vote failed and candidate was dismissed.
- `expired_no_quorum`: not enough unique voters; prepared source stays parked for manual retry.
- `cancelled`: bot/admin cancelled the poll.

Indexes:

- `(status, closes_at)` for the finalizer.
- `candidate_id` for lookup/history.
- unique `(chat_id, message_id)` where `message_id IS NOT NULL`.
- partial unique active poll globally, because the daily cycle has exactly one current poll:
  `CREATE UNIQUE INDEX ... ON meme_source_candidate_poll ((true)) WHERE status IN ('draft', 'open')`.
- partial unique active poll per candidate as an extra guard:
  `UNIQUE (candidate_id) WHERE status IN ('draft', 'open')`.

Why a poll table exists:

- Need `poll_id` before posting so callback data can be short: `mscv:{poll_id}:1`.
- Need to track chat message, close time, status, prepared source, and added source result.
- Avoid hiding lifecycle state in `meme_source_candidate.data`.

### Candidate/source lifecycle

The daily source cycle has two separate transitions:

- **Prepare**: create or reuse a `meme_source` row with `status='in_moderation'`, attach it to the candidate, and cache the parsed raw Telegram posts. This source is not visible to users.
- **Enable**: after a passed vote, move the prepared source to `status='parsing_enabled'` and let the normal storage/recommendation pipeline process the cached raw posts.

Use candidate statuses consistently:

- `discovered`: candidate is waiting for the daily source cycle.
- `prepared`: a `meme_source` row exists in `in_moderation` and a poll can refer to it.
- `promoted`: the vote passed and the prepared source was enabled.
- `dismissed`: the candidate failed the automatic cycle and should not return automatically.

`meme_source_candidate.promoted_meme_source_id` points to the prepared source as soon as it exists. The name is legacy; during this flow, the row is "prepared" until the poll passes.

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

- `1`: add source
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

- `mscv:123:1` means add source.
- `mscv:123:2` means skip.

Button labels:

- `✅ Add source 4`
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

## Daily Source Cycle

Run from a small scheduled flow or admin command. The production schedule may
check frequently (for example every 15 minutes) so early negative polls can be
closed soon after they become eligible.

Order matters:

1. Post the **Next-Day Source Report** for the last source that passed and was enabled in a previous cycle, if it has not been reported yet.
2. Close the currently `open` poll if its 24-hour window has elapsed or if it
   matches the early negative rule:
   - recompute likes/dislikes from `meme_source_candidate_vote`;
   - mark the poll `passed`, `rejected`, or `expired_no_quorum`;
   - edit the moderator-chat message so it keeps the source URL and shows
     final vote results;
   - unpin the closed voting message.
3. If the closed poll passed, enable the prepared source:
   - load `poll.prepared_meme_source_id` or the candidate's `promoted_meme_source_id`;
   - set `language_code='ru'`;
   - call `advance_meme_source(status='parsing_enabled', trigger_parse=False)`;
   - run the normal Telegram storage pipeline from cached raw posts;
   - write vote metadata into `meme_source.data`.
4. Select at most one new candidate:
   - `meme_source_candidate.status = 'discovered'`;
   - no `draft/open` poll exists globally;
   - no prior closed poll exists for the candidate;
   - URL does not already exist in `meme_source`;
   - order by `times_forwarded DESC, last_seen_at DESC`.
5. Prepare the selected candidate:
   - create or reuse a `meme_source` row with `status='in_moderation'`;
   - fetch the latest public Telegram posts once;
   - inspect the fetched posts for Cyrillic evidence;
   - if Cyrillic is absent, dismiss the candidate and stop the current run without posting a poll;
   - if Cyrillic is present, save the fetched posts into `meme_raw_telegram`;
   - mark the candidate `prepared` and store `promoted_meme_source_id`.
6. Insert `meme_source_candidate_poll` as `draft`, with `prepared_meme_source_id` and `closes_at = now() + interval '24 hours'`.
7. Send Telegram message to `TELEGRAM_MODERATOR_CHAT_ID` with callback buttons containing the new `poll_id`.
8. Update poll with `chat_id`, `message_id`, `opened_at`, `status='open'`.
9. If send fails, mark `status='cancelled'` and keep the prepared source in `in_moderation` for an admin retry.

Hard limit: exactly one active source poll at a time. The point is a steady
community ritual, not a high-volume ops feed; early-rejected non-meme sources
may be replaced before the full 24-hour window.

Message content should include:

- source URL;
- `times_forwarded`;
- when first/last seen;
- one short Cyrillic evidence snippet if available;
- one-line explanation: "Vote means: add this source to the bot. It will enter normal parsing and recommendations."

## Russian-Only Candidate Filter

The daily cycle is for the Russian-speaking moderator chat. Only candidates with Cyrillic evidence enter automatic voting.

V1 rule:

1. Create or reuse a prepared `meme_source` row with `status='in_moderation'`; raw Telegram rows require a `meme_source_id`.
2. Fetch the latest 20 public posts for the candidate URL (`https://t.me/s/<username>`) using the existing Telegram scraper.
3. Inspect recent post text and link-preview text.
4. If any Cyrillic character `[А-Яа-яЁё]` is present, the candidate is eligible:
   - save the same fetched posts into `meme_raw_telegram`;
   - keep the prepared source as `status='in_moderation'`;
   - set source language to `ru` before or during enablement.
5. If no Cyrillic is found, exclude the candidate from the automatic daily cycle:
   - do not post a poll;
   - set the prepared source to `status='parsing_disabled'`;
   - mark the candidate dismissed with `dismissed_reason='non_ru_no_cyrillic'`.

This one Telegram fetch is both the language check and the raw-post cache. Do not fetch Telegram again when the vote passes.

For v1, parse at most one candidate for this check per day. If that candidate is non-Russian, the day simply has no new poll; the cycle tries the next discovered candidate tomorrow.

Do not infer English/non-Russian sources into this flow. Non-Russian sources can still be added manually outside the daily moderator-chat cycle.

## ETL Enablement Guard

Prepared sources intentionally have raw Telegram posts before moderators approve them. Therefore the storage pipeline must gate raw-to-meme transformation on source status.

`etl_memes_from_raw_telegram_posts()` must only create or update `meme` rows from raw posts where:

```sql
meme_source.status = 'parsing_enabled'
```

Apply the same status guard to both query branches inside that ETL:

- the transformed raw-post query;
- the "raw posts not yet in `meme`" query.

This is the safety invariant for the whole flow: `in_moderation` sources may store raw posts, but they must not create user-visible memes until the vote passes and the source is enabled.

## Closing Rule

First prototype:

- voting window: 24 hours;
- quorum: 3 unique voters;
- fan floor: at least 2 likes;
- pass threshold: like share > 30%;
- admin veto can be added later, but do not block v1 on it.

Outcomes:

- `total < 3`: mark poll `expired_no_quorum`; keep the prepared source in `in_moderation`; keep the candidate `prepared`; do not repost it automatically in v1.
- `likes >= 2 AND likes / total > 0.30`: mark poll `passed`; enable the prepared source.
- otherwise: mark poll `rejected`; set the prepared source to `parsing_disabled` and dismiss candidate with `dismissed_reason='source_vote:{poll_id}'`.

Rejected sources must not return to the automatic daily cycle. If the owner wants to revisit one, they can add it manually later.

Early negative close: after the poll has been open for at least 90 minutes,
if it has 0 likes and at least 6 dislikes, close it immediately as
`rejected`, set the prepared source to `parsing_disabled`, dismiss the
candidate with `dismissed_reason='source_vote:{poll_id}:early_negative_not_meme_source'`,
write `meme_source.data.source_vote_rejection.reason='early_negative_not_meme_source'`,
and try to post the next candidate.

## Passing Source Flow

On pass:

1. Load the prepared source from `poll.prepared_meme_source_id` or `meme_source_candidate.promoted_meme_source_id`.
2. Mark the candidate `promoted`.
3. Determine language:
   - daily-cycle sources are always `language_code='ru'` because they passed the Cyrillic filter.
4. Call `advance_meme_source()`:
   - `moderator_id='source-vote:{poll_id}'`
   - `language_code='ru'`
   - `status='parsing_enabled'`
   - `trigger_parse=False`
5. Run the normal Telegram storage pipeline from cached raw posts. The pass path must not parse Telegram again.
6. Merge vote metadata into `meme_source.data`:

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
  }
}
```

7. Update poll `result_meme_source_id`.
8. Edit the moderator-chat message with final result.
9. Store enough metadata to include this source in the next daily report.

## Next-Day Source Report

The vote decides whether to add the source. The source then competes in the normal recommendation system.

Post a report to the moderator chat during the next daily source cycle after the source was enabled.

Report fields:

- source URL;
- number of parsed memes;
- number of `ok` memes added to recommendations;
- total likes and dislikes;
- number of memes with likes > dislikes;
- number of memes with dislikes > likes;
- duplicate/ad/rejected counts if available;
- current source status if it was auto-snoozed.

This report is product feedback for moderators, not a separate approval gate. Bad sources are expected to be deprioritized by recommendation quality signals and auto-snoozed by existing source health rules.

## Why This Shape

This avoids table sprawl:

- `meme_source_candidate` remains discovery queue.
- `meme_source_candidate_poll` is the chat decision lifecycle.
- `meme_source_candidate_vote` is the one-user-one-current-vote ledger.
- `meme_source.data` stores vote/report metadata after promotion.

It avoids unnecessary Telegram parsing:

- the Cyrillic check and raw-post cache happen in the same fetch;
- passing a vote enables the prepared source and reuses cached raw posts;
- the pass path uses `trigger_parse=False`.

It protects users from unapproved sources:

- prepared sources stay `in_moderation`;
- Telegram ETL only turns raw posts into memes for `parsing_enabled` sources;
- rejected sources are disabled and do not return automatically.

It also avoids counter bugs:

- no duplicate votes because `(poll_id, user_id)` is the key;
- repeated same vote only updates `updated_at`;
- switching yes to no changes exactly one row;
- displayed counters are always derived from unique vote rows.

## Prototype Scope

Ship the smallest useful version:

1. Migration + `database.py` table definitions.
2. Daily source-cycle service.
3. Source preparation service:
   - create/reuse `meme_source(status='in_moderation')`;
   - fetch latest 20 Telegram posts once;
   - detect Cyrillic;
   - save raw posts for eligible candidates.
4. Telegram ETL status guard for raw posts from prepared sources.
5. Callback handler with mutable unique votes.
6. Manual/admin command or small scheduled flow to run the daily cycle.
7. Poll closing inside the daily cycle.
8. Basic tests:
   - repeated same vote does not increase count;
   - yes -> no changes counts;
   - non-moderator-chat callback is rejected;
   - expired poll rejects new votes;
   - raw posts from `in_moderation` sources do not create memes;
   - passed poll enables candidate once and does not parse Telegram again.

Do not build weighted scout scores in v1. Record clean votes first; weighting can come after we have data.
