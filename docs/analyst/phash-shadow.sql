-- Perceptual-hash (dHash) duplicate detection — shadow readout (read-only)
-- Run: psql "$ANALYST_DATABASE_URL" -f docs/analyst/phash-shadow.sql
--
-- meme.image_hash = 64-bit dHash (images: uploaded bytes; video/animation:
-- Telegram thumbnail). v1 matches EXACT hash only; nothing is merged yet.
-- Live = status IN ('ok', 'published'). Usable hashes exclude NULL, 0 and -1.
-- All sections share one current, read-only snapshot. Current status/hash/file ID
-- can differ from their value at ingestion; this diagnostic cannot replay the
-- historical matcher or estimate precision across every past upload.
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '30s';
SELECT transaction_timestamp() AS checked_at;

\echo === Hash coverage (live memes) ===
SELECT type,
       COUNT(*) AS live,
       COUNT(*) FILTER (WHERE image_hash NOT IN (0, -1)) AS usable_hashes,
       COUNT(*) FILTER (WHERE image_hash IN (0, -1)) AS degenerate_hashes,
       COUNT(*) FILTER (WHERE image_hash IS NULL) AS unhashed,
       ROUND(100.0 * COUNT(*) FILTER (WHERE image_hash NOT IN (0, -1))
           / NULLIF(COUNT(*), 0), 1) AS usable_hash_pct
FROM meme
WHERE status IN ('ok', 'published')
GROUP BY type
ORDER BY live DESC;

\echo === Exact-hash collision groups among live memes, by type ===
-- extra_candidates counts rows beyond the first, before file-ID and time checks.
SELECT types,
       COUNT(*) AS groups,
       SUM(n) AS memes_in_groups,
       SUM(n - 1) AS extra_candidates,
       COUNT(*) FILTER (WHERE file_ids < n) AS groups_sharing_file_id
FROM (
    SELECT image_hash,
           COUNT(*) AS n,
           COUNT(DISTINCT telegram_file_id) AS file_ids,
           STRING_AGG(DISTINCT type, '+' ORDER BY type) AS types
    FROM meme
    WHERE status IN ('ok', 'published') AND image_hash NOT IN (0, -1)
    GROUP BY image_hash
    HAVING COUNT(*) > 1
) g
GROUP BY types
ORDER BY groups DESC;

\echo === Largest groups (degenerate hashes, e.g. blank frames, show up here) ===
SELECT image_hash, COUNT(*) AS n, MIN(id) AS example_id
FROM meme
WHERE status IN ('ok', 'published') AND image_hash IS NOT NULL
GROUP BY image_hash
HAVING COUNT(*) > 1
ORDER BY n DESC
LIMIT 20;

\echo === Already linked by duplicate_of: does the hash agree? ===
-- same_hash = existing dedup (file_id / OCR) and dHash agree.
SELECT d.type,
       COUNT(*) AS linked_pairs_both_hashed,
       COUNT(*) FILTER (WHERE d.image_hash = o.image_hash) AS same_hash
FROM meme d
JOIN meme o ON o.id = d.duplicate_of
WHERE d.image_hash NOT IN (0, -1) AND o.image_hash NOT IN (0, -1)
GROUP BY d.type;

\echo === Deterministic incoming-match sample for manual precision check ===
-- Sample surviving live incoming memes created since shadow deployment. Choose
-- one candidate per incoming meme, with the runtime priority (published, then ID).
-- The creation-time restriction keeps only candidates that could already exist.
-- Current publication status and hash availability still limit historical support.
-- Each incoming event receives equal sampling weight, regardless of how many
-- matching candidates its hash has. The fixed seed makes the current snapshot
-- reproducible. Save IDs and media privately before labeling; changing status,
-- hashes or inventory can change the sample on a later run.
SELECT a.id AS meme_id, b.id AS candidate_id, a.type, b.type AS candidate_type,
       a.status, b.status AS candidate_status, a.image_hash,
       a.created_at AS incoming_created_at, b.created_at AS candidate_created_at,
       COALESCE(a.duplicate_of = b.id OR b.duplicate_of = a.id, FALSE) AS ocr_linked
FROM meme a
JOIN LATERAL (
    SELECT candidate.id, candidate.type, candidate.status,
           candidate.created_at, candidate.duplicate_of
    FROM meme candidate
    WHERE candidate.image_hash = a.image_hash
      AND candidate.id != a.id
      AND candidate.status IN ('ok', 'published')
      AND candidate.telegram_file_id IS DISTINCT FROM a.telegram_file_id
      AND (candidate.created_at, candidate.id) < (a.created_at, a.id)
    ORDER BY CASE WHEN candidate.status = 'published' THEN 0 ELSE 1 END, candidate.id
    LIMIT 1
) b ON TRUE
WHERE a.status IN ('ok', 'published')
  AND a.created_at >= '2026-10-31'
  AND a.image_hash NOT IN (0, -1)
ORDER BY MD5('ff-phash-review-20261122:' || a.id::text), a.id
LIMIT 50;
COMMIT;
