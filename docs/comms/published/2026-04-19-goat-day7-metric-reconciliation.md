# Daily Post — 2026-04-19

**Channel:** @ffmemes (chat_id=-1001472939243)
**Message ID:** 220
**Status:** Published ✅
**Source data:** experiments/reports/analyst-2026-04-18.md, experiments/active/2026-04-12-goat-recency-filter.md

---

## Post Text (Russian)

GOAT эксперимент, день 7/14.

Вчера писали: сессия упала на 40%. Оказалось — мерили две разные штуки под одним именем.

«North Star = 30» — медиана реакций на пользователя в активный день. Стабильно на 30.

«Сессия = 18» — медиана длины конкретной сессии (без 30-мин паузы). Всегда была 16–21.

Никакого падения нет. Аналитик разобрался.

GOAT движок:
▪ LR 41.9% (бейслайн 39.4%)
▪ Continuation 97.5%
▪ WAU 628 — чуть ниже порога 650, смотрим

7 дней до финала.

↳ @ffmemesbot

---

## Key Metrics Referenced

| Metric | Value |
|--------|-------|
| GOAT experiment day | 7/14 (measuring until Apr 27) |
| GOAT LR | 41.9% (↑ from 39.4% baseline) |
| GOAT continuation rate | 97.5% |
| North Star (per-user-day median) | 30 — stable |
| Session median (per-session) | 18 — always been 16–21 |
| WAU | 628 (threshold: 650) |
| DAU | 271 |
| Like rate | 43.8% |
| describe_memes | 245 descriptions / 24h |
| New memes 24h | 576 |
| ok_pct | 92% |
| Bot | Online ✅ |

## Visual

Stat card (matplotlib, brand palette #FF6B35 / #1A1A2E):
- Header: GOAT recency filter · День 7/14 | @ffmemes · build in public · 19 апреля 2026
- Progress bar: 7/14 days filled orange, "измерение до 27 апреля"
- Left panel (green border): Metric reconciliation — North Star = 30 (per-user-day, stable), Сессионная медиана = 18 (per-session, always 16–21). "Никакого падения нет"
- Right panel (orange border): GOAT движок — LR 41.9% (OK), Continuation 97.5% (OK), WAU 628 (< 650 threshold), DAU 271
- Bottom bar: describe_memes 245/24ч, new memes 576/24ч, ok_pct 92%, like rate 43.8%, bot online

## Narrative

Build-in-public story: GOAT Day 7/14, and the session metric mystery is solved. Yesterday's post raised the alarm about "session length dropping 40% from 30 to 18". Analyst investigation found two different metrics were being measured under the same label: North Star = per-user-day median (30, stable), Session median = per-session (18, was always 16–21). No actual regression. GOAT engine metrics remain healthy (LR 41.9% vs 39.4% baseline, continuation 97.5%). WAU 628 slightly below 650 threshold, watching.
