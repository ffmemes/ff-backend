# Daily Post — 2026-04-05

**Channel:** @ffmemes (chat_id=-1001472939243)
**Message ID:** 205
**Status:** Published ✅
**Source data:** experiments/reports/analyst-2026-04-05.md, experiments/active/2026-03-26-cold-start-v2.md, experiments/active/2026-03-29-upload-promotion-day1.md

---

## Post Text (Russian)

1 апреля к нам пришли 62 новых юзера. Это хорошо. И плохо — они сломали North Star на 10 дней.

▪ Новый трафик с внешнего источника, низкий retention — медиана сессий за 7 дней упала с 22 до 16. Не потому что продукт стал хуже. Потому что апрельский spike ещё в окне. Уйдёт к 8 апреля.

▪ cold_start_v2 — день 11 из 14. Финал 9 апреля. Два метрика жёлтые: 10-мем доходимость 44.2% (цель >50%) и North Star 16 (цель ≥18). Но daily-медианы апреля: 17, 17, 17, 20. Норм. Без spike-когорты 10-мем reach возвращается выше 50%.

▪ Что держится уверенно: first-meme LR 27.8% при цели >20% ✓, WAU 899 при цели ≥500 ✓. Гипотеза подтверждается — качество первых мемов решает.

🟥 Параллельно upload_promo A/B. День 6. D1 retention у обеих групп ~28% — паритет. Завтра первые D7-данные. Если нет лифта — переписываем CTA или паузим.

WAU 899. Подходим к 900.

↳ @ffmemesbot

---

## Key Metrics Referenced

| Metric | Value |
|--------|-------|
| WAU | 899 (record) |
| North Star (7d rolling) | 16 (daily medians Apr 2-5: 17-20) |
| Reactions / 24h | 22,989 |
| Like rate | 38% |
| cold_start_v2 day | 11/14 (concludes Apr 9) |
| first-meme LR | 27.8% (target >20%) ✓ |
| 10-meme reach | 44.2% (target >50%) ⚠ — Apr 1 spike artifact |
| upload_promo A/B | Day 6 — D1 converged (28.1% vs 28.6%), D7 data Apr 6 |
| Apr 1 spike users | 62 new users, low retention, suppressing 7d North Star until Apr 8 |

## Visual

Stat card (900x560, brand palette #FF6B35 / #1A1A2E) with WorkSans font showing:
- Header bar: @ffmemes + date
- 3 top metric cards: WAU 899, North Star 16, Reactions 23K
- cold_start_v2 progress bar (11/14) + 4-column metrics grid
- upload_promo A/B status row
- Footer: describe_memes stats + DAU/MAU
