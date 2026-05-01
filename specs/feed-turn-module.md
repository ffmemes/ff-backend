# Feed Turn Module Refactor Brief

Status: research / implementation handoff.
Goal: make the reaction -> next meme path easier to change, test, and measure without changing product behavior.

## Why This Matters

The Feed Turn is the product's critical hot path:

```text
user taps like/dislike
-> reaction is persisted
-> next meme or popup is delivered
-> next impression row is created
-> queue refill is triggered
```

Today this is spread across these modules:

- `src/tgbot/handlers/reaction.py`
- `src/tgbot/senders/next_message.py`
- `src/tgbot/senders/meme.py`
- `src/recommendations/service.py`
- `src/recommendations/meme_queue.py`
- `src/recommendations/candidates.py`
- `src/redis.py`

The target is a deeper Module: a small Interface that owns one Feed Turn while keeping the existing implementations behind adapters until parity is proven.

## Current Invariants

- One `user_meme_reaction` row per `(user_id, meme_id)`.
- A delivered meme is considered seen when the pending `user_meme_reaction` row is inserted, even before the user reacts.
- `update_user_meme_reaction()` is the idempotency seam: it only updates rows with `reaction_id IS NULL` and returns `rowcount > 0`.
- Duplicate callback clicks must not trigger another next meme.
- Queue candidates must be `status='ok'`, language-compatible, unseen for the user, and contain `id`, `type`, `telegram_file_id`, and `recommended_by`.
- Queue refill uses a Redis lock and only generates when queue length is `<= 8`.
- Redis queue key format and queued meme JSON shape must not change during the refactor.

## Known Failure Modes To Preserve Or Fix Deliberately

- Malformed callback data can raise before persistence because the handler pattern is broad.
- Duplicate callbacks currently still run counter cache update, moderator invite check, last active update, and daily reward scheduling before DB dedupe.
- If no pending reaction row exists, the feed does not advance, but pre-dedupe side effects may already have happened.
- `Forbidden` in `send_new_message_with_meme()` marks the user blocked and returns `None`; the caller may still create a pending next-impression row.
- `TimedOut` retries after popping a meme. If Telegram actually delivered, no pending row is created for that popped meme.
- `BadRequest` disables broken media and retries; after too many failures the user gets the queue-preparing alert.
- `check_queue()` logs and swallows generation failures, so users may fall through to empty queue behavior.

Do not "clean these up" silently. Write characterization tests first, then decide which behaviors are bugs worth changing.

## Proposed Module Shape

Create a new package only after tests lock current behavior:

```text
src/feed_turn/
  __init__.py
  contracts.py        # TurnRequest, TurnResult, QueueSnapshot, CandidateBatch
  ports.py            # Protocols for queue, candidates, reactions, user info, delivery, observability
  planner.py          # pure maturity-stage / engine-plan selection
  refill.py           # queue refill orchestration
  turn.py             # FeedTurnService: one feed turn = react + find + deliver + record + refill
  adapters/
    legacy_queue.py
    legacy_candidates.py
    legacy_reactions.py
    telegram_delivery.py
    user_info.py
```

Keep these public functions import-compatible at first:

- `src.tgbot.handlers.reaction.handle_reaction`
- `src.tgbot.senders.next_message.next_message`
- `src.recommendations.meme_queue.check_queue`
- `src.recommendations.meme_queue.generate_recommendations`
- `src.tgbot.senders.meme.send_meme_to_user`

## Adapter Seams

- `ReactionLedgerPort`: wraps `create_user_meme_reaction`, `update_user_meme_reaction`, and `user_meme_reaction_exists`.
- `QueuePort`: wraps Redis LIST operations, queue length, queued IDs, and per-user refill lock.
- `CandidateRetrieverPort`: wraps `CandidatesRetriever`.
- `BlenderPort`: wraps `blend()` exactly, including `fixed_pos` and `random_seed`.
- `DeliveryPort`: wraps caption creation, keyboard creation, send/edit behavior, broken media handling, and blocked-user handling.
- `UserInfoPort`: wraps cached user info and language lookup.
- `ObservabilityPort`: structured logs / async analytics writes, never blocking Telegram delivery.

## Safe Implementation Plan

1. Freeze current behavior with characterization tests.
   Cover reaction idempotency, duplicate callbacks, positive/negative delivery path, stale queue entries, popup branch, first-meme nudge ordering, empty queue alert, `Forbidden`, `TimedOut`, `BadRequest`, and `check_queue` lock behavior.

2. Extract a pure planner.
   Move only the decision table from `generate_recommendations()`: cold start phases, growing, mature, moderator/admin quota, fixed positions, weights, and fallback chain. No Redis writes, SQL, or Telegram calls in this step.

3. Split candidate selection from enqueue.
   Keep `generate_recommendations()` as the compatibility wrapper, but introduce internal `select_candidates()` and `enqueue_candidates()` so tests can exercise the selection Interface without mutating Redis.

4. Add observability wrappers around the legacy path.
   First instrument existing behavior before moving behavior. This gives baseline metrics for parity.

5. Introduce `FeedTurnService` behind `next_message()`.
   `next_message()` should delegate to the service through legacy adapters while preserving the old function signature.

6. Move `handle_reaction()` orchestration behind the service.
   Only after delivery behavior is locked and monitored.

7. Move secondary entry points last.
   Examples: empty queue alert, language reset queue clear, upload completion queue check, broadcasts, moderator manual queue edits.

## Feature Flag And Rollback

Add a config flag such as:

```text
FEED_TURN_MODULE_ENABLED=false
```

Default it to false until tests and production telemetry prove parity.

Rollback must be a config flip, not a data migration. Keep these stable:

- Redis key format: `meme_queue:{user_id}`
- queued meme JSON shape
- `recommended_by` values
- `user_meme_reaction` write timing
- existing public function signatures

Shadow mode is allowed only for pure planning/candidate selection. Do not shadow queue writes or reaction writes.

## Test Gate

Run this focused gate before and after each phase:

```bash
pytest \
  tests/recommendations/test_blender.py \
  tests/recommendations/test_meme_queue.py \
  tests/recommendations/test_queue_correctness.py \
  tests/recommendations/test_engine_contracts.py \
  tests/recommendations/test_reaction_service.py \
  tests/tgbot/test_reaction_handler.py \
  tests/tgbot/test_first_meme_nudge.py \
  tests/test_redis.py
```

Add new tests before moving behavior:

- `tests/feed_turn/test_planner.py`
- `tests/feed_turn/test_turn_service.py`
- `tests/feed_turn/test_refill.py`
- `tests/tgbot/test_next_message_delivery.py`

Test doubles should sit at adapter seams, not inside implementation details.

## Observability Contract

The refactor is not done until Feed Turn can be monitored.

Use low-cardinality structured logs or a non-blocking analytics writer for always-on data. If a table is added, make it append-only and time-retained.

Recommended event names:

- `ff.feed_turn.started`
- `ff.feed_turn.completed`
- `ff.feed_turn.failed`
- `ff.recs.batch.generated`
- `ff.recs.engine.completed`

Recommended bounded dimensions:

- `outcome`
- `failure_class`
- `reaction_id`
- `maturity_stage`: `cold_start_1`, `cold_start_2`, `cold_start_3`, `growing`, `mature`, `moderator`
- `user_type`
- `prev_engine`
- `next_engine`
- `send_method`: `new`, `edit`, `popup`, `alert`
- `media_type`
- `language_bucket`: `ru`, `en`, `other`, `multi`
- `queue_len_bucket`: `0`, `1-2`, `3-8`, `9+`

Never use `user_id`, `meme_id`, `telegram_file_id`, caption text, queue key, or source URL as metric labels. Raw IDs can exist only in sampled logs or analytics tables.

Core metrics:

- `feed_turn_completed_total`
- `reaction_duplicate_total`
- `reaction_to_next_delivery_ms`
- `component_latency_ms` for reaction DB update, queue pop, caption build, Telegram send/edit, impression insert
- `queue_pop_attempts`
- `queue_stale_pop_total`
- `queue_refill_total`
- `recommendation_batch_duration_ms`
- `engine_candidate_count`
- `engine_empty_total`
- `blend_selected_count`
- `delivery_failure_total`
- `continuation_rate_30m`
- `next_reaction_rate`
- `fast_dislike_rate`

Recommended alerts:

- p95 `reaction_to_next_delivery_ms` regression
- queue-empty alert rate spike
- stale pop rate spike
- refill failure rate spike
- Telegram timeout rate spike
- duplicate reaction rate spike
- recommendation engine empty rate spike
- stats freshness lag

## Optional Analytics Tables

If structured logs are not enough, add these only after validating write volume.

`feed_turn_event`:

```text
turn_id
event_version
started_at
completed_at
user_id
prev_meme_id
prev_engine
reaction_id
reaction_is_new
next_meme_id
next_engine
outcome
failure_class
maturity_stage
user_type
language_bucket
send_method
media_type
queue_before
queue_after
pop_attempts
stale_pops
refill_triggered
latencies_ms JSONB
experiments JSONB
created_at
```

`feed_recommendation_batch`:

```text
batch_id
created_at
user_id
maturity_stage
limit
queue_len_before
exclude_count
engine_counts JSONB
selected_counts JSONB
fallback_used
enqueued_count
duration_ms
lock_status
error_class
```

For debugging recommendation decisions, prefer sampled or failure-only decision logs modeled after `crossposting_decision_log`.

## New Session Prompt

Use this prompt to continue in a new session:

```text
We are in /Users/ohld/Documents/GitHub/ff-backend.

Read AGENTS.md and specs/feed-turn-module.md first. Then inspect the current Feed Turn hot path:
- src/tgbot/handlers/reaction.py
- src/tgbot/senders/next_message.py
- src/tgbot/senders/meme.py
- src/recommendations/service.py
- src/recommendations/meme_queue.py
- src/recommendations/candidates.py
- src/redis.py

Goal: implement the Feed Turn Module refactor incrementally without changing behavior.

Start by writing characterization tests for the current behavior. Do not move production code until tests cover the behavior being moved.

Initial preferred slice:
1. Add tests for the pure planner shape you want.
2. Extract a pure planner from generate_recommendations() into src/feed_turn/planner.py.
3. Keep generate_recommendations() behavior and public signature unchanged.
4. Run the focused test gate from specs/feed-turn-module.md.

Architecture vocabulary:
- Module: anything with an Interface and Implementation.
- Interface: all facts callers must know, including invariants and error modes.
- Seam: where behavior can vary without editing the caller.
- Adapter: concrete implementation at a Seam.
- Deep Module: lots of behavior behind a small Interface.

Constraints:
- Preserve Redis queue key format and queued meme JSON shape.
- Preserve user_meme_reaction semantics.
- No synchronous analytics writes in the hot path.
- Do not introduce a broad abstraction unless there are at least two real adapters or it hides real complexity.
- Keep feature flag / rollback in mind for later phases.

Before finalizing, summarize:
- what behavior is now covered by tests,
- what behavior changed, if any,
- which metrics or logs were added,
- exact test commands run.
```

