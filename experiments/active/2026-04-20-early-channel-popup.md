# Experiment: Early Channel Popup (Meme #5)

**Status:** active
**Created:** 2026-04-20
**Deployed:** pending
**Measure after:** 14 days post-deploy

## Hypothesis

Moving the channel popup from meme #50 to meme #5 will increase channel subscription rate among new users, which will improve D7 retention via Telegram feed exposure (channel posts act as re-engagement push notifications). Only 30% of new users ever reach meme #50, while 90% reach meme #5 — so showing the channel earlier could reach 3× more users.

> **Note (2026-04-20 analyst):** The original spec said "75% of new users leave before meme #5" — this is incorrect. Actual data shows 89.6% of new users reach meme #5. The correct framing: 30.3% reach #50 vs 89.6% reach #5.

## Changes Required

1. Move `popup.telegram_channel` trigger from `nmemes_sent % 1000 == 50` to `nmemes_sent % 1000 == 5` in `popups.py`
2. Add subscription verification after popup click: call `check_if_user_follows_related_channel()` 30 seconds after popup interaction and log result
3. Add Prefect events for funnel tracking:
   - `ff.popup.telegram_channel.shown` (when popup is sent)
   - `ff.popup.telegram_channel.clicked` (when user taps the button)
   - `ff.popup.telegram_channel.subscribed` (when subscription verified)
4. Replace emoji-only button with a proper CTA button linking to the channel

## Success Metrics

### Primary: Channel Conversion Funnel
| Metric | How to Measure | Target |
|--------|---------------|--------|
| Popup shown rate | % of new users reaching meme #5 | Baseline ~89.6% (vs ~30.3% at meme #50) |
| Click-through rate | `reacted_at IS NOT NULL` / total shown | > 30% |
| Subscribe rate | `subscribed` events / total shown | > 10% |

### Secondary: Retention Impact
| Metric | How to Measure | Target |
|--------|---------------|--------|
| D7 retention (subscribers) | Users who subscribed and returned within 7 days | Track, no target yet |
| D7 retention (non-subscribers) | Users who saw popup but didn't subscribe | Compare against subscribers |
| Session continuation after popup | % of users who see meme #6 after popup at #5 | > 80% (no session kill) |

### Guardrails (must not regress)
| Metric | Baseline | Floor |
|--------|----------|-------|
| Session length (median, all active users) | 14 | >= 10 |
| Session length (median, new users) | 7 | >= 5 |
| Overall like rate | ~39% | >= 35% |

## Measurement Plan

Run these weekly after deploy. Replace `'DEPLOY_DATE'` with actual deploy date.

### Query 1: Popup funnel (shown → clicked → subscribed)

```sql
-- Funnel: popup shown → clicked
-- Note: "subscribed" column will only work after subscription tracking is deployed (FFM-590)
SELECT
  count(*) AS shown,
  count(*) FILTER (WHERE reacted_at IS NOT NULL) AS clicked,
  round(100.0 * count(*) FILTER (WHERE reacted_at IS NOT NULL) /
    NULLIF(count(*), 0), 1) AS click_rate_pct
FROM user_popup_logs
WHERE popup_id = 'popup.telegram_channel'
  AND sent_at > 'DEPLOY_DATE';
```

### Query 2: New user popup reach rate (guardrail)

```sql
-- % of new users (post-deploy) who reach meme #5 and continue
WITH new_users AS (
  SELECT u.id
  FROM "user" u
  WHERE u.created_at > 'DEPLOY_DATE'
),
new_user_stats AS (
  SELECT us.nmemes_sent
  FROM user_stats us
  JOIN new_users nu ON us.user_id = nu.id
)
SELECT
  count(*) AS new_users,
  count(*) FILTER (WHERE nmemes_sent >= 5) AS reached_5,
  count(*) FILTER (WHERE nmemes_sent >= 6) AS continued_past_5,
  count(*) FILTER (WHERE nmemes_sent >= 50) AS reached_50,
  round(100.0 * count(*) FILTER (WHERE nmemes_sent >= 5) / NULLIF(count(*), 0), 1) AS pct_reached_5,
  round(100.0 * count(*) FILTER (WHERE nmemes_sent >= 6) / NULLIF(count(*) FILTER (WHERE nmemes_sent >= 5), 0), 1) AS session_continuation_pct
FROM new_user_stats;
```

### Query 3: Session length guardrail

```sql
-- Median session length for active users post-deploy
SELECT
  percentile_cont(0.5) WITHIN GROUP (ORDER BY us.median_session_length) AS p50_session_length,
  percentile_cont(0.75) WITHIN GROUP (ORDER BY us.median_session_length) AS p75_session_length,
  count(*) AS users
FROM user_stats us
JOIN "user" u ON us.user_id = u.id
WHERE us.last_reaction_at > 'DEPLOY_DATE'
  AND us.median_session_length IS NOT NULL;
```

### Query 4: D7 retention by channel subscription

```sql
-- D7 retention: channel subscribers vs non-subscribers among new post-deploy users
-- Requires user_tg_chat_membership to be populated by subscription tracking
WITH new_users AS (
  SELECT u.id, u.created_at
  FROM "user" u
  WHERE u.created_at BETWEEN 'DEPLOY_DATE' AND (now() - interval '7 days')
),
channel_chat_ids AS (
  -- @fastfoodmemes = -1001152876229, @fast_food_memes = -1001305866294
  VALUES (-1001152876229), (-1001305866294)
),
subscribers AS (
  SELECT DISTINCT ut.user_id AS user_id
  FROM user_tg_chat_membership m
  JOIN user_tg ut ON m.user_tg_id = ut.id
  WHERE m.chat_id IN (SELECT column1 FROM channel_chat_ids)
),
d7_active AS (
  SELECT DISTINCT r.user_id
  FROM user_meme_reaction r
  JOIN new_users nu ON r.user_id = nu.id
  WHERE r.reacted_at BETWEEN (nu.created_at + interval '7 days') AND (nu.created_at + interval '8 days')
)
SELECT
  CASE WHEN s.user_id IS NOT NULL THEN 'subscribed' ELSE 'not_subscribed' END AS group,
  count(nu.id) AS users,
  count(d.user_id) AS retained_d7,
  round(100.0 * count(d.user_id) / NULLIF(count(nu.id), 0), 1) AS d7_pct
FROM new_users nu
LEFT JOIN subscribers s ON nu.id = s.user_id
LEFT JOIN d7_active d ON nu.id = d.user_id
GROUP BY group;
```

### Query 5: Like rate guardrail

```sql
SELECT
  sum(nlikes) AS likes,
  sum(ndislikes) AS dislikes,
  round(100.0 * sum(nlikes) / NULLIF(sum(nlikes) + sum(ndislikes), 0), 1) AS like_rate_pct
FROM user_stats
WHERE last_reaction_at > 'DEPLOY_DATE';
```

## Metrics Before

*Captured 2026-04-20 (pre-deploy)*

### Popup.telegram_channel (current at meme #50, all-time)

| Metric | Value |
|--------|-------|
| Total shown | 4,390 users |
| Total clicked | 3,311 users |
| Click-through rate | **75.4%** |

### New user funnel (90-day cohort, n=519 users with stats)

| Trigger point | Users reached | % of new users |
|---------------|--------------|----------------|
| Meme #5 | 465 | **89.6%** |
| Meme #50 (current popup) | 157 | **30.3%** |

**Moving the popup from #50 → #5 will expose it to ~3× more new users.**

### Session length (active users, last 30 days, n=1,310)

| Metric | Value |
|--------|-------|
| Median | 14 memes |
| p75 | 24 memes |
| p90 | 38 memes |

### Session length (new users only, n=292)

| Metric | Value |
|--------|-------|
| Median | 7 memes |

### Session continuation

| Threshold | Continuation rate |
|-----------|------------------|
| Continue past meme #5 (new users, n=465) | **93.5%** |
| Continue past meme #50 (new users, n=157) | 98.1% |

### D7 retention (37–7 days ago cohort, n=420)

| Metric | Value |
|--------|-------|
| D7 retention | **6.2%** |

### Channel membership (via user_tg_chat_membership)

| Channel | Tracked members |
|---------|----------------|
| -1001152876229 (@fastfoodmemes) | 1,916 |
| -1001305866294 (@fast_food_memes) | 318 |
| -1002120551028 | 233 |

### Like rate

| Metric | Value |
|--------|-------|
| Overall (from user_stats cumulative) | **39.1%** |

> **Note:** Experiment doc previously stated baseline ~50% and guardrail ≥45%. Actual measured like rate is 39.1%. Guardrail floors updated above to reflect reality.

## Metrics After

*To be filled by analyst after 14-day measurement window*

## Conclusion

*To be filled after measurement window*
