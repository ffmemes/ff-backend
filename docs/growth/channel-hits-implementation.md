# Channel hits for confirmed nonsubscribers

Owner decision, 2026-09-05: test existing channel sharing signals in the private
feed; membership checks must not delay feed requests. Keep free OCR. Defer
semantic recommendation work and a remote meme-analysis MCP until growth shows
promise.

## Delivered behavior

The `channel_hits_v1` experiment replaces one ordinary meme within the first
five sends of the first voluntary session of each UTC day. There is at most one
attempt per day. Only pre-enrolled treatment users qualify; control uses the
existing feed. Assignment has a common 14-day exposure window. The toggle is
`CHANNEL_HITS_ENABLED` (default false); enrollment alone cannot activate it.

Channel labels use the snapshot nearest 24 hours, within 20–36 hours, for posts
at least 36 hours old in the last 120 days. Images require at least 50 views;
reward posts are excluded. Each channel needs at least 20 reference posts.

Within each channel, raw forwards/views must reach p75. Rank by
`(forwards + median_views * channel_forward_rate) / (views + median_views)`;
use the within-channel percentile for comparison across languages, multiply by
existing user-source affinity, and break ties by recency. This shrinkage is a
ranking heuristic, not a statistical confidence statement. The channel pool is
refreshed in the background every ten minutes and expires after an hour.
Strict IQR outliers would leave only three memes per channel in the audited
120-day sample. See the dated distribution analysis under
`docs/analyst/research/2026-09-05-growth/channel-eligibility/`.

Eligibility requires confirmed `nonmember` status for every owned Telegram
channel publishing the meme or a known duplicate, a cache observation less
than 24 hours old, and no known prior membership. Unknown, errored or stale
states preserve exclusion. All known duplicate descendants and prior bot
deliveries, including sends without reactions, are excluded. The membership
and moderation checks run again immediately before delivery. The global
`published` status and ordinary queue policy are preserved.

Explicit links may open an available published meme and follow known duplicate
aliases. They are a user request, so subscription suppression does not apply.
Rejected or broken memes remain unavailable. `/last` can recover a reacted
published meme for correction.

## Membership and operation

`user_channel_membership` is separate from the historical positive-only table.
`CHAT_MEMBER` events update existing bot users only; event subjects never create
users or inflate activity. Old membership history remains sticky. Delayed HTTP
responses cannot overwrite a newer event. Bot administrator loss invalidates
the affected channel cache. `Update.ALL_TYPES` already includes member events.

`CHANNEL_MEMBERSHIP_SYNC_ENABLED` enables the event handlers and bounded repair
worker (default false). The worker discovers missing pairs for known users
active in the last 30 days, reconciles daily, and retries unknown states later.
Multiple app processes share a Redis lease and Telegram flood-control cooldown.
Requests are spaced; the feed performs **zero Telegram membership requests**.

Run bootstrap from the configured application environment:

```sh
python scripts/backfill_channel_membership.py --limit 100
python scripts/backfill_channel_membership.py --apply --limit 100
```

Repeat bounded apply batches until the active-user backlog is filled. The same
lease prevents overlap with the worker. `--active-days 0` includes all known
users; no channel subscriber enumeration is performed. Credentials stay in the
existing application environment; no secret arguments or files are needed.

## Enrollment, readout and rollback

1. Deploy migrations/code with both flags disabled. The duplicate lookup index
   is built concurrently; the membership migration does not backfill users.
2. Enable membership synchronization, bootstrap active users, and verify fresh
   known states and bot administrative access.
3. Refresh the channel pool with `refresh_channel_hit_pool()` in the application
   environment, then preview `scripts/channel_hit_experiment.py enroll` with
   explicit `--snapshot-at` and future `--start-at` UTC timestamps. Preview uses
   `ANALYST_DATABASE_URL`; apply uses `DATABASE_URL`. Redis must match the app.
4. Freeze the reviewed digest with `--apply --expected-cohort-digest`. Include
   all ordinary, unblocked core users with at least eight active clean-feed days,
   20 likes in the preceding 28 days, and at least 14 eligible hits. Allocate
   reproducibly 50/50, keeping all assigned users in the outcome denominator.
5. Enable `CHANNEL_HITS_ENABLED`. Confirm actual `channel_hit_v1` deliveries,
   subscription exclusions, normal-feed fallback and error/latency behavior.
6. `python scripts/channel_hit_experiment.py readout` reports actual exposure,
   unique non-self meme-link starts, new attributed invitees, and invitees who
   use the ordinary feed on days 7–13. It excludes synthetic reactions and
   retains zero-exposure users. Mature assessment is at day 28; sparse results
   remain inconclusive. SQL: `docs/analyst/channel-hits-v1.sql`.

Rollback: disable `CHANNEL_HITS_ENABLED`. Ordinary queues remain usable, and a
selected hit is checked against the flag before sending. Keep membership sync
on if healthy. Do not delete assignments, exposure history or membership
history when disabling the experiment.

## OCR duplicate fix

OCR duplicate discovery now compares all other IDs. Existing published memes
are preferred as canonical; otherwise older approved content wins. The resolver
serializes merges, rechecks status and canonical direction, and preserves
delivery/reaction history. A manually uploaded unreviewed image cannot replace
approved content. Similarity thresholds and free-model constraints are unchanged.
The fix applies on subsequent processing; no historical bulk dedup sweep is run.

## Verification state

Local implementation: focused feed/share/enrollment/readout checks passed (51),
membership checks passed (20), OCR/caller/free-model checks passed (40). Release
checkout is isolated from a pre-existing unlaunched friend-challenge change.
Full release-candidate validation and production rollout are recorded separately
when completed; this document alone is not evidence of a live deployment.
