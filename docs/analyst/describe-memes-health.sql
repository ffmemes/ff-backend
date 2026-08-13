-- Describe Memes / OCR health (read-only)
-- Run: psql "$ANALYST_DATABASE_URL" -f docs/analyst/describe-memes-health.sql
--
-- Monitoring rule: use ocr_result->>'calculated_at', NOT meme.created_at.
-- "Described" for product/dedup means description is present (OpenRouter vision).
-- Legacy easyocr rows often have calculated_at + text but no description.

\echo === Coverage (ok image memes) ===
SELECT
  COUNT(*) FILTER (WHERE status = 'ok') AS ok_memes,
  COUNT(*) FILTER (WHERE status = 'ok' AND type = 'image') AS ok_images,
  COUNT(*) FILTER (
    WHERE status = 'ok' AND type = 'image'
      AND ocr_result->>'description' IS NOT NULL
  ) AS ok_images_with_description,
  COUNT(*) FILTER (
    WHERE status = 'ok' AND type = 'image'
      AND ocr_result->>'calculated_at' IS NOT NULL
  ) AS ok_images_with_calculated_at,
  ROUND(
    100.0 * COUNT(*) FILTER (
      WHERE status = 'ok' AND type = 'image'
        AND ocr_result->>'description' IS NOT NULL
    ) / NULLIF(COUNT(*) FILTER (WHERE status = 'ok' AND type = 'image'), 0),
    1
  ) AS pct_images_with_description
FROM meme;

\echo === Throughput last 14 days (by calculated_at date, any OCR) ===
SELECT
  (ocr_result->>'calculated_at')::timestamptz::date AS day,
  COUNT(*) AS rows_with_calc_at,
  COUNT(*) FILTER (WHERE ocr_result->>'description' IS NOT NULL) AS with_description
FROM meme
WHERE ocr_result->>'calculated_at' IS NOT NULL
  AND (ocr_result->>'calculated_at')::timestamptz >= now() - interval '14 days'
GROUP BY 1
ORDER BY 1 DESC;

\echo === Freshness ===
SELECT
  MAX((ocr_result->>'calculated_at')::timestamptz) AS max_calculated_at,
  COUNT(*) FILTER (
    WHERE (ocr_result->>'calculated_at')::timestamptz >= now() - interval '24 hours'
      AND ocr_result->>'description' IS NOT NULL
  ) AS described_last_24h,
  COUNT(*) FILTER (
    WHERE (ocr_result->>'calculated_at')::timestamptz >= now() - interval '7 days'
      AND ocr_result->>'description' IS NOT NULL
  ) AS described_last_7d
FROM meme
WHERE ocr_result->>'calculated_at' IS NOT NULL;

\echo === Eligible backlog (ok images without description) ===
SELECT
  COUNT(*) AS ok_images_no_description,
  COUNT(*) FILTER (
    WHERE COALESCE((ocr_result->>'describe_failures')::int, 0) >= 3
  ) AS permanently_failed_ge3,
  COUNT(*) FILTER (
    WHERE COALESCE((ocr_result->>'describe_failures')::int, 0) < 3
  ) AS eligible_backlog
FROM meme
WHERE status = 'ok'
  AND type = 'image'
  AND telegram_file_id IS NOT NULL
  AND (ocr_result IS NULL OR ocr_result->>'description' IS NULL);

\echo === Recent describe failure reasons ===
SELECT
  COALESCE(ocr_result->>'last_failure_reason', '(none)') AS reason,
  COUNT(*) AS n
FROM meme
WHERE status = 'ok'
  AND type = 'image'
  AND COALESCE((ocr_result->>'describe_failures')::int, 0) > 0
GROUP BY 1
ORDER BY n DESC
LIMIT 15;

\echo === Models used (last 30d, successful description) ===
SELECT
  COALESCE(ocr_result->>'model', ocr_result->>'described_by', '(unknown)') AS model,
  COUNT(*) AS n
FROM meme
WHERE ocr_result->>'description' IS NOT NULL
  AND ocr_result->>'calculated_at' IS NOT NULL
  AND (ocr_result->>'calculated_at')::timestamptz >= now() - interval '30 days'
GROUP BY 1
ORDER BY n DESC
LIMIT 15;
