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

## Current Experiment (deployed 2026-04-13, measure until 2026-04-27)
- Video 1.8x scoring boost
- Weighted CTAs (top 11 get 3x weight, 10 worst removed)
- Time slot: dropped 18:00 MSK, added 11:00 MSK
- **DO NOT change scoring formula until baseline comparison is done**
- Compare: avg fwd/1k for posts after deploy vs historical baseline (18.2 fwd/1k)

## Deep Analysis Findings (from 3,400 matched DB posts, 2026-04-13)
- **Bot engagement does NOT predict channel virality.** Correlation between nlikes/lr_smoothed/engagement_score and fwd/1k is r=0.03-0.04 (essentially zero). Like rate in the formula is noise.
- **Source matters 1.8x.** Best sources avg 24.5 fwd/1k, worst avg 13.6. Source predicts forwards better than any bot metric.
- **Meme age doesn't matter.** <1 week (19.2) vs 1+ year (19.0). Recency bonus is noise.
- **Captions hurt -23%.** No caption: 18.6, has caption: 14.4 fwd/1k.
- **😁 reaction is the best forward signal.** Top quartile posts get 12.4 avg 😁 vs 6.4 in bottom quartile.
- **Forwards and bot_starts are weakly correlated.** CTA matters more than meme for conversion.

## Next Experiments (after current experiment concludes ~2026-04-27)
1. **Source-based scoring** — add meme_source bonus/penalty based on historical fwd/1k per source. Biggest untapped lever.
2. **Remove like_rate and recency from formula** — they're noise. New formula: `no_caption_bonus * video_bonus * source_quality_bonus * reach_ratio`
3. Reduce posting frequency to 5/day (data shows 5-6 is sweet spot, we're at 6)
4. Channel audience study: giveaway with deep link to identify who reads the channel
5. Track channel join/leave events via Telethon admin log
6. Add Telethon account as channel admin to unlock GetMessagePublicForwardsRequest

## Future: Per-Channel Prediction Model
Train a model that predicts whether a meme will grow the channel (high fwd/1k) BEFORE posting it. Each channel gets its own model since RU and EN audiences behave very differently (RU avg 19.4 fwd, EN avg 1.6 fwd). Features to explore: meme source, media type, OCR text length, description embeddings, time-of-day, day-of-week, meme_stats signals (even if weak individually, they may combine). Target: binary classification (above/below median fwd/1k) or regression on fwd/1k. Start simple (logistic regression on source_id + type + caption_length), graduate to embeddings if signal exists. Needs 4+ weeks of snapshot data with score_version tagging for train/test split.

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
