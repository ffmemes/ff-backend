-- Parameters: $1 inclusive UTC start, $2 exclusive UTC end. Main analysis uses sent_at, retaining nonreacted deliveries.
WITH base AS MATERIALIZED (
 SELECT r.user_id,r.meme_id,r.sent_at AS event_at,
   EXISTS(SELECT 1 FROM experiment_assignment e WHERE e.user_id=r.user_id AND e.experiment_id='channel_hits_v1') AS pilot
 FROM user_meme_reaction r JOIN "user" u ON u.id=r.user_id
 WHERE r.sent_at >= $1::timestamp - interval '1 day' AND r.sent_at < $2::timestamp
   AND u.type='user' 
   AND r.recommended_by IS NOT NULL
   AND r.recommended_by NOT IN('uploaded_meme','low_sent_pool','friend_challenge','share_link','last')
   AND r.recommended_by NOT LIKE 'broadcast%' AND r.recommended_by NOT LIKE 'friend_challenge%'
), gaps AS MATERIALIZED (
 SELECT *,extract(epoch FROM event_at-lag(event_at) OVER(PARTITION BY user_id ORDER BY event_at,meme_id))/60.0 AS gap_min
 FROM base
), assigned AS (
 SELECT g.*,t.minutes,
   sum(CASE WHEN gap_min IS NULL OR gap_min>t.minutes THEN 1 ELSE 0 END)
     OVER(PARTITION BY user_id,t.minutes ORDER BY event_at,meme_id) AS session_id
 FROM gaps g CROSS JOIN (VALUES(15),(30),(60)) t(minutes)
), sessions0 AS MATERIALIZED (
 SELECT user_id,pilot,minutes,session_id,min(event_at) AS start_at,max(event_at) AS end_at,count(*) AS reactions
 FROM assigned GROUP BY user_id,pilot,minutes,session_id
), sessions AS MATERIALIZED (
 SELECT s.*,segment FROM sessions0 s CROSS JOIN LATERAL unnest(CASE WHEN pilot THEN ARRAY['all','pilot'] ELSE ARRAY['all'] END) segment
 WHERE start_at >= $1 AND start_at < $2
), days AS (
 SELECT segment,minutes,user_id,start_at::date AS day,count(*) AS sessions,sum(reactions) AS reactions
 FROM sessions GROUP BY 1,2,3,4
), per_user AS (
 SELECT segment,minutes,user_id,count(*) AS active_days,sum(sessions) AS sessions,
   avg(sessions) AS sessions_per_active_day, count(*) FILTER(WHERE sessions>=2) AS multi_session_days
 FROM days GROUP BY 1,2,3
), user_summary AS (
 SELECT segment,minutes,count(*) AS users,count(*) FILTER(WHERE multi_session_days>0) AS users_with_multi_session_day,
   percentile_cont(0.5) WITHIN GROUP(ORDER BY sessions_per_active_day) AS median_user_mean_sessions_per_active_day
 FROM per_user GROUP BY 1,2
), day_summary AS (
 SELECT segment,minutes,count(*) AS active_user_days,sum(sessions) AS sessions,
   count(*) FILTER(WHERE sessions>=2) AS days_with_2plus,
   count(*) FILTER(WHERE sessions>=3) AS days_with_3plus,
   avg(sessions) AS mean_sessions_per_active_day,
   percentile_cont(ARRAY[0.5,0.75,0.9,0.95]) WITHIN GROUP(ORDER BY sessions) AS sessions_per_day_p50_p75_p90_p95,
   sum(least(sessions,2)) AS cap2_opportunities,
   sum(least(sessions,3)) AS cap3_opportunities,
   sum(least(sessions,4)) AS cap4_opportunities
 FROM days GROUP BY 1,2
), lengths AS (
 SELECT segment,minutes,sum(reactions) AS reactions,
   percentile_cont(ARRAY[0.5,0.75,0.9]) WITHIN GROUP(ORDER BY reactions) AS reactions_per_session_p50_p75_p90,
   percentile_cont(ARRAY[0.5,0.75,0.9]) WITHIN GROUP(ORDER BY extract(epoch FROM end_at-start_at)/60.0) AS active_session_minutes_p50_p75_p90,
   count(*) FILTER(WHERE reactions>=3) AS sessions_with_3plus_reactions
 FROM sessions GROUP BY 1,2
)
SELECT * FROM day_summary JOIN user_summary USING(segment,minutes) JOIN lengths USING(segment,minutes) ORDER BY segment,minutes

