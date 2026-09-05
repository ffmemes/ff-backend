-- Prototype only. Membership and duplicate protections match ELIGIBLE_SQL.
WITH RECURSIVE candidates AS (
    SELECT * FROM jsonb_to_recordset(CAST(:pool AS jsonb))
        AS p(id integer, percentile float, posted_at timestamp)
), family(root, id) AS (
    SELECT DISTINCT id, id FROM candidates
    UNION
    SELECT f.root, m.id FROM family f JOIN meme m ON m.duplicate_of = f.id
), seen_roots AS MATERIALIZED (
    SELECT DISTINCT f.root
    FROM family f JOIN user_meme_reaction r ON r.meme_id = f.id
    WHERE r.user_id = :user_id
), blocked_roots AS MATERIALIZED (
    SELECT DISTINCT f.root
    FROM family f JOIN crossposting cp ON cp.meme_id = f.id
    LEFT JOIN user_channel_membership cm
      ON cm.user_id = :user_id AND cm.chat_id = CASE cp.channel
        WHEN 'tgchannelru' THEN CAST(:ru_chat_id AS bigint)
        ELSE CAST(:en_chat_id AS bigint) END
    WHERE cp.channel IN ('tgchannelru', 'tgchannelen')
      AND (cm.status IS DISTINCT FROM 'nonmember' OR cm.ever_member
           OR cm.observed_at IS NULL
           OR cm.observed_at < (NOW() AT TIME ZONE 'UTC') - interval '24 hours'
           OR EXISTS (
             SELECT 1 FROM user_tg_chat_membership old
             WHERE old.user_tg_id = :user_id AND old.chat_id = cm.chat_id
           ))
), root_publications AS MATERIALIZED (
    SELECT DISTINCT cp.meme_id
    FROM candidates p JOIN crossposting cp ON cp.meme_id = p.id
    WHERE cp.channel IN ('tgchannelru', 'tgchannelen')
), scored AS (
    SELECT m.id, m.type, m.telegram_file_id, m.caption, m.language_code,
           :recommended_by AS recommended_by, coalesce(ms.nlikes, 0) AS nlikes,
           max(p.percentile) * (
             0.5 + coalesce((umss.nlikes + 1.0) /
                            nullif(umss.nlikes + umss.ndislikes + 2.0, 0), 0.5)
           ) AS personal_score,
           max(p.posted_at) AS posted_at
    FROM candidates p JOIN meme m ON m.id = p.id
    JOIN root_publications rp ON rp.meme_id = m.id
    JOIN user_language ul ON ul.user_id = :user_id AND ul.language_code = m.language_code
    LEFT JOIN meme_stats ms ON ms.meme_id = m.id
    LEFT JOIN user_meme_source_stats umss
      ON umss.user_id = :user_id AND umss.meme_source_id = m.meme_source_id
    LEFT JOIN seen_roots seen ON seen.root = m.id
    LEFT JOIN blocked_roots blocked ON blocked.root = m.id
    WHERE m.status = 'published' AND m.duplicate_of IS NULL
      AND m.telegram_file_id IS NOT NULL
      AND NOT (m.id = ANY(CAST(:excluded AS integer[])))
      AND seen.root IS NULL AND blocked.root IS NULL
    GROUP BY m.id, ms.nlikes, umss.nlikes, umss.ndislikes
)
SELECT * FROM scored
ORDER BY personal_score DESC, posted_at DESC, id
LIMIT :limit
