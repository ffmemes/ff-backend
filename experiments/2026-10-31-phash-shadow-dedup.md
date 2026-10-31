---
id: phash_shadow_v1
status: running
hypothesis: An exact 64-bit dHash match finds duplicates OCR cannot (videos, animations, text-free images) with high precision
primary_metric: precision on sampled exact-hash pairs, agreement with duplicate_of
guardrails: no merges in shadow; degenerate (blank-frame) hash groups
unit: meme
variants: shadow (logged only)
started: 2026-10-31
check_on: 2026-11-14
decided: 
result: unknown
learning: 
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
