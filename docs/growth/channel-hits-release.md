# Channel-hit pilot release

Previously, channel-published memes were excluded from the ordinary feed for every user. This release adds a disabled-by-default experiment that can show one previously unseen channel hit during the first five ordinary feed deliveries of the first daily session. The rest of the feed keeps its existing ranking.

Candidates use comparable snapshots around 24 hours after publication and a channel-specific forward-rate baseline. Delivery requires a fresh confirmed nonmember state for every owned channel where the meme or a known duplicate appeared. Missing, stale, unknown, current-member and previously observed member states suppress the candidate. Telegram membership checks run in background workers, outside the feed request.

Explicit user-requested share links can open approved published memes and resolve known duplicate links to their original. These requests do not use the proactive channel-hit membership gate.

OCR duplicate detection now works when a newer copy was described before an older one. It keeps a published original when available, otherwise the older approved copy, and preserves existing delivery/reaction history. A transaction lock prevents concurrent opposite merges. The text-similarity threshold and free-only OCR policy are unchanged; no archive-wide cleanup runs as part of deployment.

## Rollout

- Apply the owned-channel membership migration and the concurrent duplicate-lookup index migration.
- Keep `CHANNEL_HITS_ENABLED=false` until the cached candidate pool, membership backfill and frozen cohort are reviewed.
- Enable `CHANNEL_MEMBERSHIP_SYNC_ENABLED` for background repair. Use `scripts/backfill_channel_membership.py` for a bounded backfill. It supersedes the legacy `scripts/sync_channel_membership.py` for this rollout: the legacy script deletes previous positive membership observations and must not be used to populate this experiment's eligibility records. Keep the historical cache available to the new backfill.
- Enrollment previews are dry runs; applying a cohort requires its reviewed digest. Existing cohorts cannot be extended or reassigned.
- Disable `CHANNEL_HITS_ENABLED` to return all users to the ordinary feed. Membership synchronization can be disabled separately. These flags do not revoke explicit share-link access.

See [implementation and experiment protocol](channel-hits-implementation.md) and [analytical readout](../analyst/channel-hits-v1.sql).

## Validation

The isolated release passed the complete test suite on Python 3.14 with the development requirements: 754 passed, 2 skipped, and 8 subtests passed. PostgreSQL and Redis used disposable local storage and synthetic credentials. A separate migration check passed a fresh upgrade, rollback of the two new migrations, and re-upgrade, including the concurrent index. The final set-based eligibility query and cached treatment cohort are included in this validation; nonparticipants do not trigger eligibility SQL.
