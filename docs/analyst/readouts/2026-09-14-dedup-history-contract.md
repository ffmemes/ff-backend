# Deduplication history and aggregate contract — 2026-09-14

## Live event consolidation

Duplicate resolution preserves one live reaction per canonical identity. A
duplicate-side `user_meme_reaction` is moved only when that user has no reaction
on the canonical meme; when both exist, the canonical row wins and the
duplicate-side row is removed. Chat reactions apply the equivalent rule for
`(chat_id, meme_id, user_id)`.

This is intentional: the primary keys prevent a second delivery, like, or
dislike from inflating the canonical meme's live counters. `DuplicateResolution`
reports the moved and dropped counts. The duplicate `meme` row remains with its
`duplicate_of` link, so other records that reference it keep their historical
reference and can resolve through the duplicate family.

## Aggregate refreshes

The resolver refreshes the canonical `meme_stats` in the same transaction with
the full history of users who touched the canonical meme. This recomputes its
counts and normalized engagement values after moved rows are consolidated.

`meme_source_stats` runs hourly at minute 10 and recomputes from all current
live reaction rows. Moved unique reactions therefore become attributable to the
canonical meme's source; collisions remain attributable to the canonical row.

`user_meme_source_stats` runs hourly at minute 40. It recomputes all history
only for users whose `reacted_at` is within the preceding seven days. A merge
does not alter `reacted_at`, so a participant with only an older unique moved
reaction can retain a stale per-source aggregate until they react again. This
does not affect canonical meme counts or duplicate-family repeat protection.

For a manual validation merge involving older reactions, explicitly invoke the
existing user-source aggregate helper for the affected users before assessing
source-affinity output. Do not broaden the merge transaction or rewrite raw
event history without a separate product decision.
