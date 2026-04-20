# Daily Post — 2026-04-18

**Channel:** @ffmemes (chat_id=-1001472939243)
**Message ID:** 219
**Status:** Published ✅
**Source data:** experiments/reports/qa-2026-04-17-0010.md, experiments/log.jsonl (Apr 17 analyst entry), experiments/active/2026-04-12-goat-recency-filter.md

---

## Post Text (Russian)

GOAT experiment, день 6/14.

Метрики самого движка — лучше бейслайна:
▪ LR 44.3% (было 39.4%)
▪ Continuation rate 97.8% — без изменений
▪ describe_memes 245 описаний за 24ч, пайплайн живой

Сессия провалилась. 18 медиана vs 30 на бейслайне. Минус 40%.

Выглядит как корреляция с экспериментом. Но нет.

GOAT даёт 548 мемов в неделю из 167K+ суммарных реакций — меньше 1% трафика. Один идеально работающий движок не обваливает общую сессию.

Что-то другое тянет вниз. Аналитик разбирается.

WAU 627. Порог остановки эксперимента — 650. Чуть ниже, смотрим.

8 дней до финала.

↳ @ffmemesbot

---

## Key Metrics Referenced

| Metric | Value |
|--------|-------|
| GOAT experiment day | 6/14 (measuring until Apr 27) |
| GOAT LR | 44.3% (↑ from 39.4% baseline) |
| GOAT continuation rate | 97.8% |
| GOAT volume / 7d | ~548 memes out of 167K+ total reactions (<1%) |
| Session length median | 18 (vs 30 baseline, -40%) |
| WAU | 627 (threshold: 650) |
| DAU | 268 |
| Like rate | 43.8% |
| describe_memes | 245 descriptions / 24h |
| New memes 24h | 576 |
| ok_pct | 92% |
| Bot | Online ✅ |

## Visual

Stat card (1824x1128, matplotlib, brand palette #FF6B35 / #1A1A2E):
- Header: GOAT recency filter · День 6/14 | @ffmemes · build in public · 18 апреля 2026
- Progress bar: 6/14 days filled orange, "измерение до 27 апреля"
- Left panel (green border): GOAT движок — LR 44.3% ↑ от 39.4%, Continuation 97.8%, Volume/7d 548 из 167K+ реакций
- Middle panel (red border): Session length 18 vs 30 baseline, −40%, "GOAT <1% трафика → не причина"
- Right panel (red border): WAU 627, порог: 650, "чуть ниже порога"
- Bottom bar: describe_memes 245/24ч, new memes 576/24ч, ok_pct 92%, like rate 43.8%, DAU 268, Bot ✓ online

## Narrative

Build-in-public story: GOAT recency filter Day 6/14. Engine metrics are actually beating baseline (LR up from 39.4% to 44.3%, continuation steady at 97.8%). But session length dropped 40% to 18 from baseline 30. The apparent paradox: GOAT's own numbers are great, so it can't be the cause — the engine handles <1% of total traffic. Something else is pulling session down; analyst is investigating. WAU at 627, slightly below the 650 experiment stop threshold but not triggered. 8 days left in measurement window.
