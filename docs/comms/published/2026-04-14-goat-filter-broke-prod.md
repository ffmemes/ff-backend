# Daily Post — 2026-04-14

**Channel:** @ffmemes (chat_id=-1001472939243)
**Message ID:** 214
**Status:** Published ✅
**Source data:** experiments/reports/analyst-2026-04-13.md, experiments/reports/qa-2026-04-14-0547.md, experiments/active/2026-04-12-goat-recency-filter.md

---

## Post Text (Russian)

Задеплоили GOAT recency filter. Прод сломался через 6 минут.

GOAT — движок с лучшим all-time лайк-рейтингом, 97.8% continuation. Проблема: топ-мемы гоняют по кругу — один юзер получает один и тот же мем снова и снова.

Добавили per-user фильтр: убрать из выдачи мемы, на которые ты реагировал в последние 30 дней.

PR #162, merge, 6 минут — Sentry.

`column "score" does not exist` — фикс был на feature-ветке, в мерж не попал. 86 ошибок за 15 часов. Параллельно ETL pipeline лёг с другой ошибкой — invalid JOIN в etl.py, PostgreSQL не ест такое.

🟥 Ингест мемов стоит. GOAT engine падает на каждом запросе.

North Star держится на 30. WAU 676. Продукт жив — просто с дыркой в боку.

У нас 2% test coverage. Вот это и выглядит как 2% test coverage.

Деплоим фикс сегодня, потом следим 14 дней.

↳ @ffmemesbot

---

## Key Metrics Referenced

| Metric | Value |
|--------|-------|
| GOAT LR (baseline) | 39.4% |
| GOAT continuation rate | 97.8% |
| Sentry errors (goat engine) | 86 in 15h |
| North Star 7d median | 30 |
| WAU | 676 |
| Test coverage | 2% |
| Experiment window | Apr 13 → Apr 27 (14 days) |

## Visual

Stat card (1500x1020, matplotlib, brand palette #FF6B35 / #1A1A2E):
- Header: @ffmemes · build in public · 14 апреля 2026 | GOAT recency filter — задеплоили, сломали, чиним
- Left: Timeline of events (PR merged → prod broken → ETL failed → fix on branch)
- Left bottom: Error badge — 86 Sentry errors
- Right: 3 baseline metric panels (GOAT LR 39.4%, Continuation 97.8%, North Star 30)
- Right bottom: Measurement window box (Apr 13–27, success criteria, 2% test coverage note)
- Footer: ↳ @ffmemesbot

## Narrative

Build-in-public story: shipped GOAT per-user recency filter (PR #162) to prevent pool exhaustion, immediately broke prod with a missing column in the merge. ETL pipeline also broke separately. Honest disclosure of 2% test coverage as root cause. North Star held at 30 — product remains functional.
