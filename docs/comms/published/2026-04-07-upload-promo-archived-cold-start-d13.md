# Daily Post — 2026-04-07

**Channel:** @ffmemes (chat_id=-1001472939243)
**Message ID:** 207
**Status:** Published ✅
**Source data:** experiments/reports/qa-2026-04-07-0311.md, experiments/reports/analyst-2026-04-05.md, experiments/active/2026-03-26-cold-start-v2.md, experiments/active/2026-03-29-upload-promotion-day1.md

---

## Post Text (Russian)

upload_promo закрыт. Первый честный провал апреля.

Гипотеза была правильная: загрузки мемов = главный предиктор retention. Отправили новым юзерам «знаешь, что можно слать свои мемы?» после 10-го мема.

🟥 Что вышло:
▪ Upload rate: лечение 3.2%, контроль 8.8% — сообщение не помогло, буквально наоборот
▪ D1 retention: обе группы ~28% — паритет, ноль сигнала
▪ D7 данные так и не пришли, но итог уже ясен

«Дид ю ноу» не работает. Нужен момент кайфа, а не информирование.

▪ cold_start_v2 — день 13 из 14. First-meme LR держится на 27.8% при цели >20%. WAU 899. Когорт 1 апреля сегодня выходит из 7d-окна — завтра чистые числа.

9 апреля — объявляем итоги главного эксперимента.

↳ @ffmemesbot

---

## Key Metrics Referenced

| Metric | Value |
|--------|-------|
| WAU | 899 |
| North Star (daily) | 17–20 (7d rolling suppressed by Apr 1 spike, aging out today) |
| Reactions/day | 26K |
| Active users (24h) | 342 |
| New memes (24h) | 618 |
| ok_pct | 92% |
| cold_start_v2 day | 13/14 (concludes Apr 9) |
| First-meme LR | 27.8% (target >20%) ✓ |
| upload_promo treatment upload rate | 3.2% vs control 8.8% — negative signal |
| upload_promo D1 retention | ~28% both groups — parity |

## Visual

Stat card (900x560, WorkSans-Medium, brand palette #FF6B35 / #1A1A2E) with:
- Header: @ffmemes + "build in public" + date
- Left card (red border): upload_promo АРХИВИРУЕМ — bar chart treatment vs control upload rate, D1 retention parity, takeaway
- Right card (green border): cold_start_v2 День 13 из 14 — progress bar, 3-metric grid (First-meme LR 27.8%, WAU 899, North Star 17-20)
- Bottom row: 4 DB health metrics (26K reactions, 342 users, 618 memes, ok_pct 92%)
- Footer: @ffmemesbot
