# Content Plan — @ffmemes

~1 post per day. All posts in Russian. CEO approves each post.

Visual rule: every post should have an image (screenshot, chart, meme from DB, or diagram). No text-only posts.

---

## Categories

### A: Feature Spotlights

Deep dives into what the bot can do. One feature per post.

| # | Topic | Status | Visual | Notes |
|---|-------|--------|--------|-------|
| A1 | Inline meme search | BLOCKED | Bot screenshot of inline results | Wait for E2E test |
| A2 | Group chat AI agent | READY | Screenshot of bot replying in group | Include "Add to chat" deep link button |
| A3 | Burger economy | READY | Screenshot of /kitchen + /leaderboard | What burgers are, how to earn/spend |
| A4 | OCR meme descriptions | BLOCKED | Before/after: meme + extracted text | Wait for OCR_ENABLED=True |
| A5 | Stars purchases | READY | Screenshot of buy menu | Buy burgers with Telegram Stars |
| A6 | How recommendations work | READY | Diagram: "your like -> better memes" | Non-technical, simplified |
| A7 | Upload your own memes | READY | Screenshot of upload flow | Show the moderation queue |
| A8 | Weekly leaderboard | READY | Screenshot of /leaderboard | Top meme senders get burgers |

### B: Historical / Lore

The journey. Build-in-public spirit. Reference the archive in `lore/`.

| # | Topic | Visual |
|---|-------|--------|
| B1 | "How it started" — vc.ru throwback, Oct 2020 | Screenshot of vc.ru article header |
| B2 | "535K memes collected, 205K approved" | Infographic: funnel from sources to ok |
| B3 | "22M reactions and counting" | Chart: reactions growth over time |
| B4 | "9 recommendation engines" | Simple diagram of engine names |
| B5 | "AI agents now run the bot" | Agent org chart from COMPANY.md |
| B6 | Channel milestones throwback | Screenshots of old posts from archive |
| B7 | "From 2.5K to 22K users" | Timeline graphic |

### C: Data Insights

Real numbers. Charts. From Analyst reports or direct DB queries.

| # | Topic | Visual | Data source |
|---|-------|--------|-------------|
| C1 | Weekly engagement snapshot | DAU/WAU/MAU chart | docs/analyst/metrics.sql |
| C2 | Meme of the week (most liked) | The actual meme | meme_stats ORDER BY nlikes |
| C3 | Top meme sources this week | Bar chart by like rate | meme_source_stats |
| C4 | Session length update | Line chart | North Star metric |
| C5 | Like rate by language/time | Heatmap or bar chart | user_meme_reaction analysis |
| C6 | "X new memes today from Y sources" | Simple stat card | Daily meme count |
| C7 | Interesting data anomaly | Chart + explanation | Ad-hoc analysis |

### D: Engagement / Interactive

Drive action. Giveaways, CTAs, voting.

| # | Topic | Mechanism | Status |
|---|-------|-----------|--------|
| D1 | "77 burgers to first 100 clickers" | Deep link `?start=giveaway_77` | BLOCKED (needs handler) |
| D2 | "Rate which features to build" | Star voting InlineKeyboard | BLOCKED (needs handler) |
| D3 | "Add bot to your group chat" | `?startgroup=true` deep link button | READY (needs constant) |
| D4 | "Share your meme stats" card | PIL-generated personalized card | BLOCKED (needs implementation) |

### E: Recurring Formats

Predictable cadence. Readers know when to expect what.

| # | Format | Schedule | Status |
|---|--------|----------|--------|
| E1 | Weekly burger balance report | Sunday 14:00 MSK | BLOCKED (needs Prefect flow) |
| E2 | "Meme of the day" — top meme from yesterday | Daily morning | READY |
| E3 | Weekly what-we-shipped digest | Friday | READY |

### F: Behind-the-scenes / Engineering

Nerdy content. How things work under the hood.

| # | Topic | Visual |
|---|-------|--------|
| F1 | "How our parsers collect memes" | Pipeline diagram |
| F2 | "Watermark algorithm finds the quietest corner" | Before/after meme with watermark |
| F3 | "PostgreSQL handles 22M reactions" | Architecture diagram |
| F4 | "Prefect runs 23 scheduled jobs" | Dashboard screenshot or job list |
| F5 | "AI describes every meme" — vision model pipeline | Meme + generated description side-by-side |

---

## Suggested First 2 Weeks

| Day | Post | Category | Why this order |
|-----|------|----------|----------------|
| 1 | Origin story throwback (B1) | Lore | Sets the "we're back" tone |
| 2 | Daily pulse: X memes from Y sources (C6) | Data | Easy, automated, shows scale |
| 3 | Burger economy reveal (A3) | Feature | Teases what's coming |
| 4 | Meme of the day (E2) | Recurring | Start the daily habit |
| 5 | 535K memes collected (B2) | Lore | Impressive number |
| 6 | Upload your own memes (A7) | Feature | Actionable CTA |
| 7 | First weekly burger report (E1) | Recurring | Sunday 14:00 MSK |
| 8 | Watermark algorithm (F2) | Engineering | Nerdy but fun |
| 9 | 77 burger giveaway (D1) | Engagement | Drive clicks |
| 10 | Meme of the week (C2) | Data | The actual best meme |
| 11 | Group chat AI (A2) | Feature | "Add to chat" button |
| 12 | AI agents run the bot (B5) | Lore | Mind-blowing for audience |
| 13 | Weekly engagement snapshot (C1) | Data | DAU/WAU/MAU chart |
| 14 | What we shipped this week (E3) | Recurring | Friday digest |

---

## Visual Guidelines

Every post should include an image. Types:

1. **Bot screenshots** — for feature spotlights (A-category). Take via browse skill or manually.
2. **Memes from DB** — for "meme of the day/week" (C2, E2). Already watermarked.
3. **Charts** — for data posts (C-category). Generate with PIL/matplotlib using brand palette.
4. **Diagrams** — for engineering posts (F-category). Simple, clean, brand colors.
5. **Infographics** — for lore posts (B-category). Timeline/funnel style.

See [brand-guide.md](brand-guide.md) for colors, fonts, and chart styling.

---

## Blockers

| What | Blocks | Action needed |
|------|--------|---------------|
| E2E test of inline search | A1 | Run E2E tests on bot |
| OCR_ENABLED=False | A4 | Enable OCR in prod |
| Giveaway deep link handler | D1 | Code: new handler in start.py |
| Star voting handler | D2 | Code: new InlineKeyboard handler |
| Personalized stats card | D4 | Code: PIL card generation |
| Weekly report Prefect flow | E1 | Code: weekly_report.py |
| ADD_TO_GROUP_DEEPLINK | A2, D3 | Code: constant in constants.py |
| Chart generation utils | C1, C3, C4 | Code: matplotlib/PIL helpers |
