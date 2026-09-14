# Deduplication history and aggregate contract — 2026-09-14

## Live event consolidation

The user explicitly selected the first reaction as the truth for duplicate memes
on 2026-09-14. This supersedes the previous canonical-side collision policy.

Duplicate resolution preserves one coherent live reaction row per user and
canonical identity. An explicit reaction wins over an unreacted exposure; among
explicit reactions the earliest `reacted_at` wins, followed by earliest
`sent_at`. A missing reaction timestamp sorts after a known timestamp. If neither
row has a reaction, the earliest exposure wins. The winning row carries its
original recommendation attribution and timestamps together with its reaction.
Chat collisions similarly preserve the earliest reaction. Exact timestamp ties
retain the canonical row; standard OCR dedup chooses the canonical identity
consistently (published first, otherwise the oldest meme ID).

The duplicate meme remains with its `duplicate_of` link. Other historical
references can still resolve through the duplicate family. Reaction consolidation
prevents repeated exposures or conflicting votes from inflating live counters.

## Aggregate refreshes

The resolver refreshes canonical `meme_stats` in the merge transaction using the
full history of users who touched that meme. It also immediately recalculates
`user_meme_source_stats` for duplicate-side participants and both involved
sources, including older reactions. Source pairs with no surviving reactions are
removed; unrelated preferences are preserved. The periodic source-preference
batch shares the merge transaction lock so it cannot overwrite the refresh with
a pre-merge snapshot.

Global `meme_source_stats` continues to refresh on its existing hourly schedule.
Redis delivery eligibility checks reject duplicate rows and reject the canonical
meme for any user with a surviving exposure or reaction.
