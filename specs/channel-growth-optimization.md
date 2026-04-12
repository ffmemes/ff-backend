# Channel Growth Optimization

## Status: DEPLOYED (2026-04-13)

## What Shipped
- Telethon stats collector (every 6h) reads views, forwards, reactions, comments from @fastfoodmemes (RU, 2185 subs) and @fast_food_memes (EN, 626 subs)
- Schema: crossposting table extended with telegram_message_id, caption_text, score_version, views, forwards, reactions, comments, reactions_detail (JSONB). New crossposting_snapshots table for time-series. New channel_daily_stats for subscriber tracking.
- Post capture: log_meme_sent() now stores telegram_message_id and caption_text at post time
- channel_invited_count: separate metric for sc_% deep links (channel->bot conversions), distinct from invited_count (s_% in-bot shares)
- Video priority: 1.8x scoring boost (data: 28.2 vs 15.7 fwd/1k across 11K posts)
- CTA optimization: removed 10 worst CTAs (<16 fwd/1k), top 11 get 3x weight
- Time slot: dropped 18:00 MSK evening slot (10.2 fwd/1k, worst), added 11:00 MSK

## Key Data Findings (from 11,117 RU channel posts)
- Videos get 1.8x more forwards than photos
- Optimal frequency: 5-6 posts/day (sweet spot)
- Best time: 09:00-15:00 UTC. Worst: 18:00 UTC (21:00 MSK)
- CTA matters ~2x: challenge/dare CTAs outperform passive ones
- Forward rate varies 40x across posts (1.0 to 42.8 fwd/1k)
- RU channel drives ~70-100 new bot users/month via deep links
- Posts with 21+ reactions get 37% more forwards (correlation, not causation)

## Metrics to Track
- Primary: forwards_per_1k_views at 24h
- Secondary: bot_starts via deep link (user_deep_link_log WHERE deep_link LIKE 'sc_%')
- Supporting: subscriber_count delta per day, in-channel reactions

## Next Experiments (prioritized)
1. Monitor video priority impact (deployed, measure in 2 weeks)
2. Monitor CTA weighting impact (deployed, measure in 2 weeks)
3. Monitor time slot change impact (deployed, measure in 2 weeks)
4. Reduce posting frequency to 4/day with only top-scored memes (hypothesis: fewer but better posts = more forwards per post)
5. Channel audience study: giveaway with deep link to identify who reads the channel, cross-reference with bot users
6. Track channel join/leave events via Telethon admin log
7. Add Telethon account as channel admin to unlock GetMessagePublicForwardsRequest (see who reposts publicly)

## Architecture
- Stats collector: src/flows/crossposting/stats_collector.py (Prefect flow, every 6h)
- Scoring: src/crossposting/service.py (get_next_meme_for_tgchannelru/en)
- CTAs: src/flows/crossposting/meme.py (CTAS list, weighted by repetition)
- Env vars: TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION_STRING (same as e2e smoke tests)
- Schedule: scripts/serve_flows.py (RU: 8,10,11,12,14,16 MSK, EN: 8,10,14,18,20 MSK)

## Backfill
Full snapshot of all channel posts saved to channel_posts_snapshot.json (15K posts, 11.6M views RU + 672K views EN). To be bulk-inserted into crossposting_snapshots after migration runs.

## Dependencies
- Telethon session string must be in Prefect worker container env
- Session expires on security events, requires manual re-generation via scripts/generate_session_string.py
