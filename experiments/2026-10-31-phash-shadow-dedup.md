---
id: phash_shadow_v1
status: running
hypothesis: An exact 64-bit dHash match finds duplicates OCR cannot (videos, animations, text-free images) with high precision
primary_metric: precision on sampled exact-hash pairs, agreement with duplicate_of
guardrails: no merges in shadow; degenerate (blank-frame) hash groups
unit: meme
variants: shadow (logged only)
started: 2026-10-31
check_on: 2026-11-28
decided: 
result: November 22 precision sample 50/50 true duplicates, 0 unknown. Registered point threshold 48/50 passed. Live merging remains pending.
learning: Exact nondegenerate hashes passed a current live-inventory audit with production candidate ordering.
code: src/storage/deduplication/image_hash.py, meme.image_hash, scripts/admin/backfill_image_hash.py
readout: docs/analyst/phash-shadow.sql
---

# Experiment: Perceptual hash dedup (shadow)

Shipped 2026-10-31 in PR #381. Every new upload stores a 64-bit dHash in
`meme.image_hash` (video/animation: Telegram thumbnail). After a non-duplicate upload,
a live meme with the same hash is logged as `phash shadow match`; nothing is merged.
About 40% of sends go to memes OCR cannot dedup, which is the gap this targets.

Known limits: backfill skips videos/animations; upload and backfill hash different
bytes (exact match may miss a few pairs); hashes 0/-1 are not matched.

No check date or ship rule was set. Next step: run `phash-shadow.sql` after the
backfill, label sample pairs for precision, then decide on merges (Hamming distance is
the upgrade path).

- 2026-10-31: check_on set to 2026-11-14: run scripts/admin/backfill_image_hash.py for 30 days of images, then docs/analyst/phash-shadow.sql; turn merging on only if a 50-pair sample shows >=95% true duplicates.


## November 22 precision check

One agent reviewed a fixed sample of 50 pairs from a single snapshot at 14:35 UTC. All 50 were judged duplicates, with zero unknowns (30 images, 19 videos, one animation). Each incoming item had one earlier candidate with a different Telegram file identifier. The selector excluded degenerate hashes and preferred published items, then the lowest ID. Motion review used six frames across each clip plus full-file identity or audio checks. The 95% two-sided exact interval for 50/50 is about 92.9% to 100%.

The registered sample threshold of 48/50 passed. The point estimate applies to a retrospective sample of surviving live items and a single reviewer. Actual ingest-time statuses can differ. The private pair manifest records the selections and verdicts. Merging is still off. November 28 is an implementation decision about a reversible, monitored rollout. [Review](../docs/analyst/readouts/2026-11-22-experiment-check.md).
