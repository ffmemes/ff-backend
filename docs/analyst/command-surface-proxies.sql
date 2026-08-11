-- Command / product-surface proxies
-- Private DMs (incl. slash commands) land in message_tg with chat_id > 0.
-- Companion notes: docs/product/surface-and-commands.md

-- 1) Core feed
SELECT
  COUNT(*) FILTER (WHERE reacted_at > now() - interval '7 days') AS reactions_7d,
  COUNT(DISTINCT user_id) FILTER (WHERE reacted_at > now() - interval '7 days') AS users_7d,
  COUNT(*) FILTER (WHERE reacted_at > now() - interval '30 days') AS reactions_30d,
  COUNT(DISTINCT user_id) FILTER (WHERE reacted_at > now() - interval '30 days') AS users_30d,
  ROUND(
    100.0 * COUNT(*) FILTER (
      WHERE reacted_at > now() - interval '7 days' AND reaction_id = 2
    ) / NULLIF(
      COUNT(*) FILTER (
        WHERE reacted_at > now() - interval '7 days' AND reaction_id IS NOT NULL
      ),
      0
    ),
    1
  ) AS skip_pct_7d
FROM user_meme_reaction
WHERE reacted_at > now() - interval '30 days';

-- 2) Deep-link buckets
SELECT
  CASE
    WHEN deep_link IS NULL OR deep_link = '' THEN '(empty)'
    WHEN deep_link ~ '^(m|s)_' THEN 'share_meme'
    WHEN deep_link ~ '^sc_' THEN 'channel_share'
    WHEN deep_link = 'kitchen' THEN 'kitchen'
    WHEN deep_link LIKE 'giveaway%' THEN 'giveaway'
    WHEN deep_link = 'wrapped' THEN 'wrapped'
    WHEN deep_link = 'inline_search_request' THEN 'inline_search_request'
    ELSE 'other'
  END AS bucket,
  COUNT(*) AS events,
  COUNT(DISTINCT user_id) AS users
FROM user_deep_link_log
WHERE created_at > now() - interval '30 days'
GROUP BY 1
ORDER BY events DESC;

-- 3) Economy / treasury
SELECT type, COUNT(*) AS n, COUNT(DISTINCT user_id) AS users, SUM(amount) AS sum_amount
FROM treasury_trx
WHERE created_at > now() - interval '30 days'
GROUP BY type
ORDER BY n DESC;

-- 4) Secondary surfaces (unique users 30d)
SELECT 'feed_reactors' AS feature, COUNT(DISTINCT user_id) AS users
FROM user_meme_reaction
WHERE reacted_at > now() - interval '30 days'
UNION ALL
SELECT 'uploaders', COUNT(DISTINCT user_id)
FROM meme_raw_upload
WHERE created_at > now() - interval '30 days'
UNION ALL
SELECT 'inline_searchers', COUNT(DISTINCT user_id)
FROM inline_search_logs
WHERE searched_at > now() - interval '30 days'
UNION ALL
SELECT 'bot_chat_payers', COUNT(DISTINCT user_id)
FROM treasury_trx
WHERE type = 'bot_reply_payment' AND created_at > now() - interval '30 days'
ORDER BY users DESC;

-- 5) Private slash commands from message_tg (chat_id > 0 = private DMs)
SELECT
  lower(split_part(split_part(trim(text), ' ', 1), '@', 1)) AS command,
  COUNT(*) AS n,
  COUNT(DISTINCT user_id) AS users
FROM message_tg
WHERE date > now() - interval '30 days'
  AND chat_id > 0
  AND text LIKE '/%'
GROUP BY 1
ORDER BY n DESC;

-- 6) Private DM volume vs groups
SELECT
  CASE WHEN chat_id > 0 THEN 'private' ELSE 'group_or_channel' END AS kind,
  COUNT(*) AS messages,
  COUNT(DISTINCT user_id) AS users
FROM message_tg
WHERE date > now() - interval '30 days'
GROUP BY 1;
