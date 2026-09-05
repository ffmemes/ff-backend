WITH base AS (
 SELECT r.user_id,r.meme_id,r.sent_at AS event_at,r.recommended_by
 FROM user_meme_reaction r JOIN experiment_assignment e ON e.user_id=r.user_id AND e.experiment_id='channel_hits_v1'
 JOIN "user" u ON u.id=r.user_id
 WHERE r.sent_at >= $1::timestamp-interval '1 day' AND r.sent_at < $2::timestamp
 AND u.type='user' AND r.recommended_by IS NOT NULL
 AND r.recommended_by NOT IN('uploaded_meme','low_sent_pool','friend_challenge','share_link','last')
 AND r.recommended_by NOT LIKE 'broadcast%' AND r.recommended_by NOT LIKE 'friend_challenge%'
), gaps AS (
 SELECT *,lag(event_at) OVER(PARTITION BY user_id ORDER BY event_at,meme_id) AS previous_at FROM base
), assigned AS (
 SELECT *,sum(CASE WHEN previous_at IS NULL OR event_at-previous_at>interval '30 minutes' THEN 1 ELSE 0 END)
 OVER(PARTITION BY user_id ORDER BY event_at,meme_id) AS session_id FROM gaps
)
SELECT user_id,session_id,min(event_at) AS start_at,max(event_at) AS end_at,count(*) AS deliveries,
 count(*) FILTER(WHERE recommended_by='direct') AS direct_deliveries
FROM assigned GROUP BY user_id,session_id
HAVING min(event_at)>=$1 AND min(event_at)<$2 ORDER BY user_id,start_at

