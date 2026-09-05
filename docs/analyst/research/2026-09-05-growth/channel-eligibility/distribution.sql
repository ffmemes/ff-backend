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
), periods AS (
 SELECT '120d' AS period,* FROM labels
 UNION ALL SELECT '30d',* FROM labels WHERE posted_at>=timestamp '2026-08-06'
)
SELECT channel,period,count(*) AS posts,
 percentile_cont(ARRAY[0.05,0.25,0.5,0.75,0.9,0.95,0.99]) WITHIN GROUP(ORDER BY views) AS views_quantiles,
 percentile_cont(ARRAY[0.05,0.25,0.5,0.75,0.9,0.95,0.99]) WITHIN GROUP(ORDER BY forwards) AS forwards_quantiles,
 percentile_cont(ARRAY[0.05,0.25,0.5,0.75,0.9,0.95,0.99]) WITHIN GROUP(ORDER BY f1k) AS f1k_quantiles,
 min(views) AS min_views,max(views) AS max_views,max(forwards) AS max_forwards,max(f1k) AS max_f1k,
 count(*) FILTER(WHERE views<25) AS below25views,
 count(*) FILTER(WHERE views<50) AS below50views,
 count(*) FILTER(WHERE views<100) AS below100views,
 count(*) FILTER(WHERE forwards<3) AS below3forwards,
 1000.0*sum(forwards)/sum(views) AS aggregate_f1k
FROM periods GROUP BY channel,period ORDER BY channel,period;
