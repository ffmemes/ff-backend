# Meme Deduplication

## Current State

17% of parsed memes are marked as duplicates. Current mechanisms:

1. **ETL single-media filter** (~80% of the 17%) — carousel posts removed. Not true dedup.
2. **Telegram forwarded_url** — same-source repost detection at ETL time.
3. **OCR text trigram similarity** (DISABLED) — PostgreSQL `pg_trgm` operator `%` on extracted text. Min 12 chars. Requires `OCR_ENABLED=true`.

The text-based dedup (`find_meme_duplicate()` in `src/storage/service.py:205`) uses:
```sql
AND (M.ocr_result ->> 'text') % '{imagetext}'  -- trigram similarity > 0.3
```
GIN index exists: `idx_meme_ocr_text_gin`

## What's NOT Detected

- Cross-source duplicates (same meme in different TG channels)
- Cropped/resized/recompressed versions
- Memes with different watermarks from different channels
- Video duplicates (OCR only works on images)
- Text-on-image memes where text is slightly different

## Cheap Dedup Plan (No Paid OCR)

### Stage A: Exact media fingerprint
- Hash the downloaded bytes before watermarking
- Store hash on meme table
- Exact match catches identical reposts (same quality, same crop)
- Cost: zero. Just a SHA256.

### Stage B: Perceptual image hashing
- Use `imagehash` library (phash, dhash, whash)
- Hamming distance threshold catches resized/recompressed
- Store 64-bit hash on meme table
- Nearest-neighbor search: hamming distance < 10 = likely duplicate
- Cost: CPU only, ~5ms per image. Library is free.

### Stage C: Video keyframe hashing
- Extract 1-3 representative frames from videos/GIFs
- Apply perceptual hash to frames
- Cost: needs ffmpeg, adds ~1s per video.

### Stage D: Caption + metadata heuristics
- Normalize caption text (strip URLs, emojis, boilerplate)
- Trigram similarity on cleaned captions (already have pg_trgm)
- Cluster by (media dimensions, file size, publish timestamp window)
- Cost: pure SQL, zero external deps.

### Stage E: OCR only for uncertain bucket
- Run cheap OCR (Tesseract, free) only on visually-similar-but-not-identical pairs
- This reduces OCR volume from "all memes" to "~5% of memes"
- Cost: Tesseract is free but accuracy is lower than Modal

## Implementation Priority

1. Stage A (exact hash) — trivial, do first
2. Stage B (perceptual hash) — highest impact, catches most cross-source dupes
3. Stage D (caption similarity) — already partially built, just needs ETL integration
4. Stage C (video keyframes) — lower priority, videos are 7% of content
5. Stage E (targeted OCR) — only if A+B+D miss significant dupes

## Source Discovery via Reposts

Telegram parser already captures `forwarded_url` for forwarded posts. This data can be used to:
1. Find which external channels our sources repost from
2. Auto-discover high-quality sources (channels frequently reposted by our best sources)
3. Build a repost graph to understand the meme distribution network

Query to find most-reposted-from channels:
```sql
SELECT forwarded_url, COUNT(*)
FROM meme_raw_telegram
WHERE forwarded_url IS NOT NULL
GROUP BY forwarded_url
ORDER BY COUNT(*) DESC;
```
