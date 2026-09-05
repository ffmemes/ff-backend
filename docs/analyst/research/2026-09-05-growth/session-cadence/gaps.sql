-- Same parameters and clean delivery exclusions as summary.sql.
WITH base AS MATERIALIZED (
 SELECT r.user_id,r.meme_id,r.sent_at AS event_at,
 EXISTS(SELECT 1 FROM experiment_assignment e WHERE e.user_id=r.user_id AND e.experiment_id='channel_hits_v1') AS pilot
 FROM user_meme_reaction r JOIN "user" u ON u.id=r.user_id
 WHERE r.sent_at >= $1::timestamp-interval '1 day' AND r.sent_at<$2::timestamp
 AND u.type='user'  AND r.recommended_by IS NOT NULL
 AND r.recommended_by NOT IN('uploaded_meme','low_sent_pool','friend_challenge','share_link','last')
 AND r.recommended_by NOT LIKE 'broadcast%' AND r.recommended_by NOT LIKE 'friend_challenge%'
), gaps AS (
 SELECT *,extract(epoch FROM event_at-lag(event_at) OVER(PARTITION BY user_id ORDER BY event_at,meme_id)) AS seconds
 FROM base
), bins AS (
 SELECT pilot,
 CASE WHEN seconds<5 THEN '01: <5s' WHEN seconds<15 THEN '02: 5-15s' WHEN seconds<60 THEN '03: 15-60s'
 WHEN seconds<300 THEN '04: 1-5m' WHEN seconds<900 THEN '05: 5-15m' WHEN seconds<1800 THEN '06: 15-30m'
 WHEN seconds<3600 THEN '07: 30-60m' WHEN seconds<7200 THEN '08: 1-2h' WHEN seconds<14400 THEN '09: 2-4h'
 WHEN seconds<28800 THEN '10: 4-8h' WHEN seconds<43200 THEN '11: 8-12h' WHEN seconds<86400 THEN '12: 12-24h'
 ELSE '13: >=24h' END AS gap,seconds
 FROM gaps WHERE event_at>=$1 AND seconds IS NOT NULL
)
SELECT segment,gap,count(*) AS intervals FROM bins CROSS JOIN LATERAL unnest(CASE WHEN pilot THEN ARRAY['all','pilot'] ELSE ARRAY['all'] END) segment GROUP BY 1,2 ORDER BY 1,2

