# OCR queue priority — 2026-09-14

## Decision

Describe Memes now prioritizes images that users are seeing now, while keeping
capacity for new uploads, newly parsed images, and a bounded share of the old
backlog. It no longer orders the OCR backlog by all-time `meme_stats.nlikes`.

For the scheduled nine-image batch, the queue is:

| Tier | Slots | Selection |
| --- | ---: | --- |
| Recent user uploads | 2 | Pending images from a `user upload` source created in the last 7 days |
| Recently shown | 5 | Pending images among the latest 500 indexed delivery events from the last 7 days, ordered by each image's latest send |
| Other fresh images | 1 | Other pending images created in the last 7 days |
| Oldest pending | 1 | Oldest remaining pending image, to prevent permanent starvation |

If upload capacity is unused, it moves to recently shown images. If recently
shown capacity is then unused, it moves to fresh images. Tiers exclude IDs
selected by earlier tiers, so one image cannot use two slots.
If no active tiers can use the remaining capacity, it returns to the old
backlog so an otherwise healthy run still uses its entire batch. If the old
backlog tier is empty, its reserved capacity instead returns to recent sends,
then fresh images.

## Production evidence

Read-only production queries on 2026-09-14 found:

- 234,351 eligible pending image descriptions.
- 1,200 were created in the preceding 7 days; 21 were recent user uploads.
- 25,517 pending images had been sent to users during that 7-day window.
- `user_meme_reaction` contains about 26.1 million rows (about 9.6 GB), so a
  full-history `MAX(sent_at)` by meme is not acceptable in a 15-minute job.

The existing `user_meme_reaction(sent_at, meme_id, user_id)` index can scan the
newest 500 delivery rows backward. `EXPLAIN ANALYZE` for the delivery tier was
about 18 ms and found 392 eligible pending images in that bounded sample.

The whole new query, before the pending-image index exists, took about 1.37 s
and read about 141k buffers. The bounded delivery branch was cheap; selecting
fresh and oldest images still performed broad scans of the 636k-row `meme`
table. Migration `d4e6f8a1b3c5` therefore adds a concurrent partial index on
`meme.created_at` only for eligible pending image descriptions. It matches the
fresh and fairness predicates and avoids making that repeated broad scan part
of the scheduled queue path.

## Scope and limits

`last_sent_at` is intentionally not denormalized onto `meme`. The delivery
event table and its existing time index supply a current signal with no
write-path changes and no historical reaction aggregation. The 500-event cap
means the tier reflects the active delivery stream rather than attempting a
complete ranked history. This is the intended behavior for OCR coverage that
protects the live feed.

The index should be applied before relying on the scheduled queue change in
production. After deployment, verify the candidate query with `EXPLAIN
ANALYZE`, check that the index is selected for fresh and oldest tiers, and
monitor the share of each selected tier plus the oldest pending age.
