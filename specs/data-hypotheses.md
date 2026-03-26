# Data Analysis: Hypotheses & Findings

> Production database: 2026-03-13. 22M reactions, 22K users, 2 years of data.

## H1: ENGAGEMENT — Meme Types & Sessions

**Finding**: Image-dominant sessions are 4.3x longer than video-dominant (median 30 vs 10 memes). Videos have higher LR (59% vs 54%) but kill throughput. 98% of sessions are image-dominant.

**Action**: Keep feed mostly images. Don't push more video content. Occasional high-quality videos are fine.

## H2: SOURCES — Retention Correlation

**Finding**: 7x retention gap between best (45% D7) and worst (6% D7) sources in first 10 memes. Uploaded memes and t.me/admeme are churn drivers. t.me/rugag, t.me/fastfoodmemes are retention-positive.

**Action**: Cold start should use proven retention sources. Exclude uploaded memes from first 10.

## H3: FRESHNESS — Age vs Quality

**Finding**: Freshness hypothesis REJECTED. Older memes have HIGHER LR (45.3% at 90+ days vs 40.6% at <1 day). Age is a quality filter — old memes survived natural selection.

**Action**: Don't prioritize recency. Don't penalize old memes.

## H4: COLD START — Drop-off Analysis

**Finding**: 25% of users leave within first 5 memes. Only 55% reach meme 10. Magic number is ~30 memes (87.6% reaction rate, stable LR). Meme #1 has lowest engagement (62% react, 11.7s median).

**Action**: First 5 memes are make-or-break. Optimize cold start for immediate "wow."

## H5: POWER USERS — Segmentation

**Finding**: 5 segments from Bounced (<10 reactions) to Power (1000+). LR peaks at Engaged (100-999) at 54.9%. Bounced = 33% of all users. Tryout-to-Casual conversion shows +5pp LR jump.

**Action**: Target re-engagement for Tryout users (10-29 reactions, 2+ day absence).

## H6: ENGINES — Performance Comparison

**Finding**: 3 engines actively hurt the feed (goat 20% LR, low_sent_pool 27%, less_seen_meme_and_source 31%) at 14% combined traffic. Best: like_spread_and_recent (50.4% LR), multiply_all_scores (46.9%).

**Action**: Remove bad engines from user traffic. Scale up winners.

## H7: TIME — Time-of-Day Patterns

**Finding**: 13pp LR swing between morning (49%) and night (36%). Moscow timezone audience. Day of week barely matters.

**Action**: Consider time-aware quality thresholds at night.

## Summary: Prioritized Actions

| # | Action | Impact | Effort | Source |
|---|--------|--------|--------|--------|
| 1 | Kill 3 bad engines | +3-5pp LR | Low | H6 |
| 2 | Optimize cold start first-5 | +10-20% activation | Medium | H2, H4 |
| 3 | Scale up winning engines | +1-2pp LR | Low | H6 |
| 4 | Remove churn sources from cold start | Less early bounce | Low | H2 |
| 5 | Don't prioritize freshness | Avoid anti-pattern | None | H3 |
| 6 | Re-engage tryout users | Convert to casuals | Medium | H5 |
| 7 | Higher quality at night | +2-3pp night LR | Medium | H7 |
