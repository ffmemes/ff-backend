# Cohort Analysis: Super Users vs Churned (2026-03-29)

> Production data: 15K users with reactions, 22M+ reactions.

## Cohort Definitions

| Cohort | Definition | Users |
|--------|-----------|-------|
| **Super user** | active_span >= 7d, sessions >= 3, last active < 30d ago | 733 (4.9%) |
| **One-session churn** | 1 session, < 20 memes seen | 6,609 (43.9%) |
| **Tried briefly** | 2+ sessions, active_span < 2d, gone > 30d | 710 (4.7%) |
| **Other** | Everyone else | 7,016 (46.6%) |

## Key Metrics by Cohort

| Metric | Super Users | One-Session Churn | Tried Briefly |
|--------|-------------|-------------------|---------------|
| Avg memes seen | 21,830 | 6 | 43 |
| Avg sessions | 497 | 1 | 2 |
| Avg active days | 214 | 1 | 2 |
| Avg hours spent | 57.6h | 0.02h | 0.1h |
| Memes/session | 36 | 6 | 18 |
| Like rate | 52% | 43% | 47% |
| Avg invited users | 0.5 | 0.0 | 0.0 |

## Finding 1: Power Law — Top 5% = 90% of Everything

Top 5% of users (by memes seen) consume **90.4% of all memes** and generate **59.4% of all invites**.

## Finding 2: Magic Number = 30 Memes on Day 1

| First day memes | Users | Retention |
|-----------------|-------|-----------|
| 1-3 | 2,250 | 21.3% |
| 4-7 | 2,343 | 26.3% |
| 8-15 | 3,234 | 33.0% |
| 16-30 | 2,104 | **46.0%** |
| 31-50 | 1,386 | **57.8%** |
| 51-100 | 981 | **71.4%** |
| 100+ | 886 | **85.2%** |

Inflection at 30 memes: retention doubles from 33% to 46%. Confirms H4 from data-hypotheses.md.

## Finding 3: Upload = Habit Feature (37% of super users, 0.2% of churned)

| Feature | Super Users | Churned |
|---------|-------------|---------|
| Uploaded memes | **36.8%** | 0.2% |
| Inline search | **18.7%** | 0.2% |

Upload and inline sharing are **repeat use case** features. Users who upload check how their memes performed. Users who share via inline use it in chats regularly.

## Finding 4: Like Rate Barely Predicts Retention — Depth Does

| First hour like rate | Retention |
|---------------------|-----------|
| High (>=60%) | 29.5% |
| Mid (45-60%) | 29.7% |
| Low (30-45%) | 26.6% |
| Very low (<30%) | 20.2% |

Only ~10pp spread. **Session depth is 10x better predictor than like rate.** Confirms: dislike = skip, not rejection.

## Finding 5: Super Users Skip Faster

| Metric | Super Users | Churned |
|--------|-------------|---------|
| Median reaction time | 6.2s | 7.5s |
| % under 2s | 11.8% | 6.2% |
| Like rate on <2s | **17.5%** | 38.2% |
| Like rate on 5-30s | 46.6% | 44.1% |

Super users developed a TikTok-like swipe rhythm: skip fast, engage slow. Fast reactions (<2s) are overwhelmingly skips (82.5% dislike), not a sign of bad content.

## Finding 6: Source Diversity Drives Retention

| Metric | Super Users | Churned |
|--------|-------------|---------|
| Avg sources liked | 218 | 2.6 |
| Top source % | 12.2% | 65.9% |

Churned users are stuck in 2-3 sources. Cold start should expose more sources faster.

## Finding 7: TG Premium Users Retain 2.3x Better

| | Super Rate | Churn Rate |
|---|-----------|------------|
| Premium | **9.1%** | 32.4% |
| Non-premium | 3.9% | 46.4% |

## Finding 8: Super User Invites Produce Better Users

- Invited by super user: **14.8%** become super users
- Invited by others: **10.4%** become super users

## Finding 9: Acquisition Channel Quality Varies Massively

- `inline_search_request`: 11.8% super user rate (best)
- `organic`: 1.2% super user rate
- `tapps_*` (Telegram app store): **0%** super user rate across all variants
- `likefollowbot`: **0%** super user rate

## Finding 10: Content Fatigue Risk

Super users: 477 memes/week (Jan) -> 330 memes/week (Mar) = **30% decline** over 12 weeks.
Like rate stable (~50%) — not quality issue, likely exhaustion of fresh content.

18% of super users inactive last 2 weeks. 14% declining 50%+.

## Recommended Experiments

### EXP-1: First-Session Depth Optimization
**Goal**: Get more users past 30 memes on Day 1
**How**: Reduce friction in first session — faster queue refills, better cold start meme quality, possibly onboarding message after meme #5 encouraging to keep going
**Measure**: % of new users reaching 30 memes (baseline from adaptive cold start experiment)

### EXP-2: Upload Promotion on Day 1
**Goal**: Introduce upload feature to new users early
**How**: After ~10-15 memes, send a popup/message explaining they can upload their own memes. Show how many people liked an uploaded meme (social proof)
**Measure**: Upload rate in first 7 days; D7 retention for uploaders vs non-uploaders

### EXP-3: Inline Search Onboarding
**Goal**: Teach sharing habit early
**How**: After first like streak (3+ likes in a row), show tip about @ffmemesbot inline sharing in other chats
**Measure**: Inline search usage D7; session frequency for inline users

### EXP-4: Fast-Skip Scoring Fix
**Goal**: Stop penalizing memes that get fast-skipped by super users
**How**: In meme_stats computation, either exclude reactions < 2s from like rate, or weight them differently. Fast skip by super user != bad meme
**Measure**: Feed quality for new users (LR, session length) after rescoring

### EXP-5: Re-engagement for Declining Super Users
**Goal**: Recover the 129 inactive + 104 declining super users
**How**: Send a message with "You haven't seen memes in a while, here's what's fresh" — personalized, best memes from their top sources since last active
**Measure**: Reactivation rate, session depth after re-engagement

### EXP-6: Kill Trash Acquisition Channels
**Goal**: Stop wasting content on 0% retention channels
**How**: Track acquisition quality by deep_link. deprioritize or block tapps/likefollowbot traffic if they consume server resources with no retention
**Measure**: Server cost per retained user by channel
