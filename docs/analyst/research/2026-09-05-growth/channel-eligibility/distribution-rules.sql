-- Read-only mature 24h image distributions. No user, post, or meme IDs output.
-- Same fixed cutoff and indexed channel/message snapshot lookup as inventory.sql.
WITH labels AS MATERIALIZED (
 SELECT cp.channel,cp.created_at AS posted_at,
 ss.views,ss.forwards,1000.0*ss.forwards/ss.views AS f1k
 FROM crossposting cp JOIN meme m ON m.id=cp.meme_id
 JOIN LATERAL (
  SELECT s.views,s.forwards FROM crossposting_snapshots s
  WHERE s.channel=cp.channel AND s.telegram_message_id=cp.telegram_message_id
  AND s.meme_id=cp.meme_id AND s.snapshot_at BETWEEN cp.created_at+interval '20 hours' AND cp.created_at+interval '36 hours'
  AND s.views>0 AND s.forwards IS NOT NULL
  ORDER BY abs(extract(epoch FROM s.snapshot_at-(cp.created_at+interval '24 hours'))) LIMIT 1
 ) ss ON true
 WHERE cp.channel IN('tgchannelru','tgchannelen')
 AND cp.created_at>=timestamp '2026-05-08' AND cp.created_at<timestamp '2026-09-03 12:00'
 AND m.type='image' AND coalesce(cp.score_version,1)<>0
 AND m.status='published' AND m.telegram_file_id IS NOT NULL AND m.duplicate_of IS NULL
)
, stats AS (
 SELECT channel,
  percentile_cont(0.25) WITHIN GROUP(ORDER BY f1k) AS p25,
  percentile_cont(0.75) WITHIN GROUP(ORDER BY f1k) AS p75,
  percentile_cont(0.9) WITHIN GROUP(ORDER BY f1k) AS p90,
  percentile_cont(0.5) WITHIN GROUP(ORDER BY views) AS prior_views,
  sum(forwards)::float/sum(views) AS baseline_rate
 FROM labels GROUP BY channel
), scored AS MATERIALIZED (
 SELECT l.*,s.p25,s.p75,s.p90,s.prior_views,s.baseline_rate,
  1000.0*(l.forwards+s.baseline_rate*s.prior_views)/(l.views+s.prior_views) AS shrunk_f1k
 FROM labels l JOIN stats s USING(channel)
), score_cuts AS (
 SELECT channel,
  percentile_cont(0.75) WITHIN GROUP(ORDER BY shrunk_f1k) AS shrunk_p75,
  percentile_cont(0.9) WITHIN GROUP(ORDER BY shrunk_f1k) AS shrunk_p90
 FROM scored GROUP BY channel
), rules AS (
 SELECT s.*,q.shrunk_p75,q.shrunk_p90,r.rule,r.included
 FROM scored s JOIN score_cuts q USING(channel)
 CROSS JOIN LATERAL (VALUES
  ('raw_p75',s.f1k>=s.p75),
  ('raw_p90',s.f1k>=s.p90),
  ('iqr_outlier',s.f1k>s.p75+1.5*(s.p75-s.p25)),
  ('shrunk_p75',s.views>=50 AND s.shrunk_f1k>=q.shrunk_p75),
  ('shrunk_p90',s.views>=50 AND s.shrunk_f1k>=q.shrunk_p90),
  ('raw_p75_and_3forwards',s.views>=50 AND s.forwards>=3 AND s.f1k>=s.p75)
 ) r(rule,included)
)
SELECT channel,rule,
 count(*) FILTER(WHERE included) AS pool120,
 count(*) FILTER(WHERE included AND posted_at>=timestamp '2026-08-06') AS pool30,
 percentile_cont(0.5) WITHIN GROUP(ORDER BY forwards) FILTER(WHERE included) AS median_forwards,
 min(forwards) FILTER(WHERE included) AS minimum_forwards,
 min(views) FILTER(WHERE included) AS minimum_views,
 count(*) FILTER(WHERE included AND f1k>=p75) AS raw_p75_overlap,
 max(p75) AS raw_p75_cut,max(p90) AS raw_p90_cut,
 max(p75+1.5*(p75-p25)) AS iqr_cut,
 max(shrunk_p75) AS shrunk_p75_cut,max(shrunk_p90) AS shrunk_p90_cut,
 max(prior_views) AS prior_views,max(baseline_rate)*1000.0 AS baseline_f1k
FROM rules GROUP BY channel,rule ORDER BY channel,rule;
