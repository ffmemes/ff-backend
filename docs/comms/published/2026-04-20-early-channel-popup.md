# Daily Post — 2026-04-20

**Channel:** @ffmemes (chat_id=-1001472939243)
**Message ID:** 221
**Status:** Published ✅
**Source data:** experiments/active/2026-04-20-early-channel-popup.md, experiments/active/2026-04-12-goat-recency-filter.md, experiments/reports/qa-2026-04-20-0009.md

---

## Post Text (Russian)

Сейчас предлагаем подписаться на @ffmemes на 50-м меме — туда доходят 30% новых пользователей.

Запускаем новый эксперимент: передвигаем popup на мем #5.

▪ 89.6% новых доходят до мема #5
▪ Только 30.3% доходят до мема #50
▪ CTR текущего popup: 75.4% — люди реально подписываются

Гипотеза: подписка на канал = посты в ленте = лучший D7 retention. Проверяем за 14 дней.

GOAT фильтр идёт день 8/14. Финал 27 апреля.

describe_memes опять rate-limited. 0/20 прошлой ночью — уже третий раз за неделю. Смотрим.

↳ @ffmemesbot

---

## Key Metrics Referenced

| Metric | Value |
|--------|-------|
| New users reaching meme #5 | 89.6% |
| New users reaching meme #50 | 30.3% |
| Channel popup CTR (all-time) | 75.4% |
| GOAT experiment day | 8/14 (measuring until Apr 27) |
| Active users 24h | 247 |
| Reactions 24h | 19,724 |
| ok_pct 24h | 93% |
| describe_memes | 0/20 (rate limited) |

## Visual

Stat card (matplotlib, brand palette #FF6B35 / #1A1A2E):
- Header: Новый эксперимент: popup на мем #5 | @ffmemes · build in public · 20 апреля 2026
- Left panel (orange border): Horizontal bar chart comparing reach at meme #50 (30.3%, gray) vs meme #5 (89.6%, orange). "→ 3× больший охват". CTR 75.4%.
- Right panel (green border): System status — GOAT день 8/14, активных 24ч 247, реакций 24ч 19,724, ok_pct 93%, describe_memes rate limit

## Narrative

New experiment announcement: moving the Telegram channel popup from meme #50 to meme #5. Key insight: 89.6% of new users reach meme #5 vs only 30.3% reach meme #50 — 3× more reach for the same popup. Existing CTR of 75.4% is strong, meaning users who see the popup do subscribe. Hypothesis: earlier channel subscription = channel posts in Telegram feed = better D7 retention via re-engagement. 14-day measurement window starting on deploy. GOAT experiment on day 8/14, still running healthy. describe_memes persistent rate-limiting flagged.
