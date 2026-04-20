# Daily Post — 2026-04-04

**Channel:** @ffmemes (chat_id=-1001472939243)
**Message ID:** 204
**Status:** Published ✅
**Source data:** experiments/reports/analyst-2026-04-03.md, experiments/active/2026-03-29-upload-promotion-day1.md

---

## Post Text (Russian)

Запустили эксперимент. Ждали 5 дней. Оказалось — данных нет.

▪ Гипотеза простая: юзеры, которые загружают мемы сами, остаются в 3x дольше. Загрузчик = суперюзер. Поэтому запустили A/B: новым юзерам после 10-го мема — предложение загрузить свой мем. Половина — контроль, без сообщения.

▪ День 5 → аналитик идёт за данными → колонок user.data и uploaded_by_user_id в проде нет. Эксперимент работал, трекинг — нет.

🟥 Классика: зашипили фичу, забыли зашипить измерение. Фиксим схему, результаты позже.

▪ Параллельно крутится cold_start_v2 — уже день 9 из 14. Через 5 дней финал.

▪ Пока держится: first-meme LR 33.3% (цель >20% ✅), доходимость до 10-го мема 56.5% (цель >50% ✅), WAU 884 ✅. North Star 15 — ниже цели, но mature-юзеры стабильно на 20. Разбавление новичками, не регрессия.

9 апреля — выводы по cold_start_v2. Смотрим.

↳ @ffmemesbot

---

## Key Metrics Referenced

| Metric | Value |
|--------|-------|
| cold_start_v2 day | 9/14 (concludes Apr 9) |
| First-meme LR | 33.3% (target >20%) |
| 10-meme reach rate | 56.5% (target >50%) |
| WAU | 884 |
| North Star | 15 (mature users: 20) |
| upload_promo A/B | Day 6 — tracking broken (user.data / uploaded_by_user_id missing in prod) |

## Visual

Stat card (800x480, brand palette #FF6B35 / #1A1A2E) showing:
- cold_start_v2 progress bar (9/14)
- 4 metric cards (first-meme LR, 10-meme reach, WAU, North Star)
- upload promo tracking broken status
