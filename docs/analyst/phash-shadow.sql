-- Perceptual-hash (dHash) duplicate detection — shadow readout (read-only)
-- Run: psql "$ANALYST_DATABASE_URL" -f docs/analyst/phash-shadow.sql
--
-- meme.image_hash = 64-bit dHash (images: uploaded bytes; video/animation:
-- Telegram thumbnail). v1 matches EXACT hash only; nothing is merged yet.
-- Live = status IN ('ok', 'published').

\echo === Hash coverage (live memes) ===
SELECT type,
       COUNT(*) AS live,
       COUNT(image_hash) AS hashed,
       ROUND(100.0 * COUNT(image_hash) / NULLIF(COUNT(*), 0), 1) AS hashed_pct
FROM meme
WHERE status IN ('ok', 'published')
GROUP BY type
ORDER BY live DESC;

\echo === Exact-hash collision groups among live memes, by type ===
-- would_be_merges = memes beyond the first in each group.
SELECT types,
       COUNT(*) AS groups,
       SUM(n) AS memes_in_groups,
       SUM(n - 1) AS would_be_merges,
       COUNT(*) FILTER (WHERE file_ids < n) AS groups_sharing_file_id
FROM (
    SELECT image_hash,
           COUNT(*) AS n,
           COUNT(DISTINCT telegram_file_id) AS file_ids,
           STRING_AGG(DISTINCT type, '+' ORDER BY type) AS types
    FROM meme
    WHERE status IN ('ok', 'published') AND image_hash IS NOT NULL
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
WHERE d.image_hash IS NOT NULL AND o.image_hash IS NOT NULL
GROUP BY d.type;

\echo === Sample same-hash live pairs for manual precision check (GET /admin/memes/{id}) ===
SELECT a.id AS meme_id, b.id AS candidate_id, a.type, b.type AS candidate_type,
       a.status, b.status AS candidate_status, a.image_hash,
       (a.duplicate_of = b.id OR b.duplicate_of = a.id) AS ocr_linked
FROM meme a
JOIN meme b ON b.image_hash = a.image_hash AND b.id < a.id
WHERE a.status IN ('ok', 'published') AND b.status IN ('ok', 'published')
  AND a.telegram_file_id IS DISTINCT FROM b.telegram_file_id
ORDER BY random()
LIMIT 50;
