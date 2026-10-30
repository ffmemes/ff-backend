SELECT c.channel||':'||coalesce(c.telegram_message_id::text,'na') post_id, CASE WHEN c.channel='tgchannelru' THEN 'ru' ELSE 'en' END ch,
 c.channel, c.meme_id, c.telegram_message_id msg_id, to_char(c.created_at,'YYYY-MM-DD"T"HH24:MI:SS') posted_at_utc,
 to_char(c.created_at,'IYYY-"W"IW') iso_week,
 extract(hour from c.created_at + interval '3 hours')::int hour_msk, extract(isodow from c.created_at + interval '3 hours')::int dow_msk,
 c.forwards, c.views, c.reactions, c.comments, round(1000.0*c.forwards/nullif(c.views,0),2) f1k, c.score_version,
 round(extract(epoch from now()-c.created_at)/86400.0,1) post_age_d,
 m.meme_source_id, ms.type src_type, replace(coalesce(ms.data->>'name',''),E'\t',' ') src_name, ms.url src_url,
 to_char(m.created_at,'YYYY-MM-DD"T"HH24:MI:SS') meme_created_at, to_char(m.published_at,'YYYY-MM-DD"T"HH24:MI:SS') meme_published_at,
 round(extract(epoch from c.created_at-m.created_at)/86400.0,2) age_created_d, round(extract(epoch from c.created_at-m.published_at)/86400.0,2) age_published_d,
 (c.caption_text IS NOT NULL AND c.caption_text<>'') has_caption,
 dl.score_version dl_sv, dl.candidate_pool_size dl_pool, dl.cand->>'rank' dl_rank, dl.cand->>'nlikes' dl_nlikes, dl.cand->>'ndislikes' dl_ndislikes,
 dl.cand->>'nmemes_sent' dl_nmemes_sent, dl.cand->>'raw_impr_rank' dl_raw_impr_rank, dl.cand->>'invited_count' dl_invited,
 dl.cand->>'pre_inbot_share_clicks' dl_share_clicks, dl.cand->>'lr_factor' dl_lr_factor, dl.cand->>'src_signal' dl_src_signal, dl.cand->>'final_score' dl_final_score,
 st.nlikes ms_nlikes, st.ndislikes ms_ndislikes, st.nmemes_sent ms_nmemes_sent, round(st.lr_smoothed::numeric,4) ms_lr_smoothed, st.raw_impr_rank ms_raw_impr_rank, st.invited_count ms_invited,
 m.language_code meme_lang,
 regexp_replace(coalesce(m.ocr_result->>'text',''),'\s+',' ','g') ocr_text,
 regexp_replace(coalesce(m.ocr_result->>'description',''),'\s+',' ','g') ocr_description
FROM crossposting c JOIN meme m ON m.id=c.meme_id LEFT JOIN meme_source ms ON ms.id=m.meme_source_id LEFT JOIN meme_stats st ON st.meme_id=c.meme_id
LEFT JOIN LATERAL (
  SELECT d.score_version, d.candidate_pool_size, (SELECT e FROM jsonb_array_elements(d.candidates) e WHERE (e->>'meme_id')::bigint=c.meme_id LIMIT 1) cand
  FROM crossposting_decision_log d
  WHERE d.channel=c.channel AND d.picked_meme_id=c.meme_id AND d.decided_at BETWEEN c.created_at-interval '1 day' AND c.created_at+interval '1 hour'
  ORDER BY abs(extract(epoch from d.decided_at-c.created_at)) LIMIT 1) dl ON true
WHERE c.created_at > now()-interval '180 days' AND c.channel IN ('tgchannelru','tgchannelen')
  AND coalesce(c.score_version,1)<>0 AND m.type='image'
ORDER BY c.channel, c.created_at
