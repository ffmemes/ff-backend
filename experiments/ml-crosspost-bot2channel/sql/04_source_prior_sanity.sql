-- Leakage-safe source prior: mean f1k of earlier same-source channel posts
\set ON_ERROR_STOP on

WITH posts AS (
  SELECT
    cp.meme_id,
    cp.created_at AS posted_at,
    cp.telegram_message_id,
    m.meme_source_id
  FROM crossposting cp
  JOIN meme m ON m.id = cp.meme_id
  WHERE cp.channel = 'tgchannelru'
    AND cp.created_at > now() - interval '180 days'
    AND cp.created_at < now() - interval '36 hours'
    AND m.type = 'image'
    AND cp.telegram_message_id IS NOT NULL
),
labels AS (
  SELECT DISTINCT ON (p.meme_id)
    p.meme_id, p.posted_at, p.meme_source_id,
    s.views, s.forwards,
    1000.0 * s.forwards / NULLIF(s.views, 0) AS f1k
  FROM posts p
  JOIN crossposting_snapshots s
    ON s.channel = 'tgchannelru'
   AND s.telegram_message_id = p.telegram_message_id
   AND s.snapshot_at BETWEEN p.posted_at + interval '18 hours'
                         AND p.posted_at + interval '36 hours'
   AND s.views > 0
  ORDER BY p.meme_id,
    abs(extract(epoch from (s.snapshot_at - (p.posted_at + interval '24 hours'))))
),
-- all labeled history for prior (extend window)
hist AS (
  SELECT
    cp.meme_id,
    cp.created_at AS posted_at,
    m.meme_source_id,
    s.forwards,
    1000.0 * s.forwards / NULLIF(s.views, 0) AS f1k
  FROM crossposting cp
  JOIN meme m ON m.id = cp.meme_id
  JOIN LATERAL (
    SELECT s.views, s.forwards
    FROM crossposting_snapshots s
    WHERE s.channel = 'tgchannelru'
      AND s.telegram_message_id = cp.telegram_message_id
      AND s.snapshot_at BETWEEN cp.created_at + interval '18 hours'
                            AND cp.created_at + interval '36 hours'
      AND s.views > 0
    ORDER BY abs(extract(epoch from (s.snapshot_at - (cp.created_at + interval '24 hours'))))
    LIMIT 1
  ) s ON true
  WHERE cp.channel = 'tgchannelru'
    AND cp.created_at > now() - interval '360 days'
    AND m.type = 'image'
    AND cp.telegram_message_id IS NOT NULL
),
with_prior AS (
  SELECT
    l.meme_id,
    l.f1k,
    l.forwards,
    (
      SELECT avg(h.f1k)
      FROM hist h
      WHERE h.meme_source_id = l.meme_source_id
        AND h.posted_at < l.posted_at
        AND h.posted_at > l.posted_at - interval '90 days'
    ) AS src_prior_f1k,
    (
      SELECT count(*)
      FROM hist h
      WHERE h.meme_source_id = l.meme_source_id
        AND h.posted_at < l.posted_at
        AND h.posted_at > l.posted_at - interval '90 days'
    ) AS src_prior_n
  FROM labels l
)
SELECT
  count(*) AS n,
  count(*) FILTER (WHERE src_prior_n >= 3) AS n_prior_ge3,
  round(corr(src_prior_f1k, f1k)::numeric, 3) AS r_prior_f1k,
  round(corr(src_prior_f1k, forwards::float)::numeric, 3) AS r_prior_fwd,
  round(avg(f1k - src_prior_f1k)::numeric, 2) AS avg_resid_f1k
FROM with_prior
WHERE src_prior_f1k IS NOT NULL;

-- prior quintiles
WITH posts AS (
  SELECT cp.meme_id, cp.created_at AS posted_at, cp.telegram_message_id, m.meme_source_id
  FROM crossposting cp
  JOIN meme m ON m.id = cp.meme_id
  WHERE cp.channel = 'tgchannelru'
    AND cp.created_at > now() - interval '180 days'
    AND cp.created_at < now() - interval '36 hours'
    AND m.type = 'image'
    AND cp.telegram_message_id IS NOT NULL
),
labels AS (
  SELECT DISTINCT ON (p.meme_id)
    p.meme_id, p.posted_at, p.meme_source_id,
    s.forwards, 1000.0 * s.forwards / NULLIF(s.views, 0) AS f1k
  FROM posts p
  JOIN crossposting_snapshots s
    ON s.channel = 'tgchannelru'
   AND s.telegram_message_id = p.telegram_message_id
   AND s.snapshot_at BETWEEN p.posted_at + interval '18 hours'
                         AND p.posted_at + interval '36 hours'
   AND s.views > 0
  ORDER BY p.meme_id,
    abs(extract(epoch from (s.snapshot_at - (p.posted_at + interval '24 hours'))))
),
hist AS (
  SELECT cp.meme_id, cp.created_at AS posted_at, m.meme_source_id,
    1000.0 * s.forwards / NULLIF(s.views, 0) AS f1k
  FROM crossposting cp
  JOIN meme m ON m.id = cp.meme_id
  JOIN LATERAL (
    SELECT s.views, s.forwards FROM crossposting_snapshots s
    WHERE s.channel = 'tgchannelru' AND s.telegram_message_id = cp.telegram_message_id
      AND s.snapshot_at BETWEEN cp.created_at + interval '18 hours'
                            AND cp.created_at + interval '36 hours'
      AND s.views > 0
    ORDER BY abs(extract(epoch from (s.snapshot_at - (cp.created_at + interval '24 hours'))))
    LIMIT 1
  ) s ON true
  WHERE cp.channel = 'tgchannelru' AND cp.created_at > now() - interval '360 days'
    AND m.type = 'image' AND cp.telegram_message_id IS NOT NULL
),
with_prior AS (
  SELECT l.f1k, l.forwards,
    (SELECT avg(h.f1k) FROM hist h
     WHERE h.meme_source_id = l.meme_source_id AND h.posted_at < l.posted_at
       AND h.posted_at > l.posted_at - interval '90 days') AS src_prior_f1k
  FROM labels l
),
q AS (
  SELECT *, ntile(5) OVER (ORDER BY src_prior_f1k) AS q5
  FROM with_prior WHERE src_prior_f1k IS NOT NULL
)
SELECT q5, count(*) n,
  round(avg(src_prior_f1k)::numeric, 2) avg_prior,
  round(avg(f1k)::numeric, 2) avg_f1k,
  round(avg(forwards)::numeric, 2) avg_fwd
FROM q GROUP BY 1 ORDER BY 1;
