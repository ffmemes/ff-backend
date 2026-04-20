# Daily Post — 2026-04-16

**Channel:** @ffmemes (chat_id=-1001472939243)
**Message ID:** 216
**Status:** Published ✅
**Source data:** experiments/reports/analyst-2026-04-15.md, experiments/reports/analyst-2026-04-16.md (partial), experiments/log.jsonl (Apr 15-16), experiments/active/2026-04-12-goat-recency-filter.md

---

## Post Text (Russian)

describe_memes не работает уже сутки.

Было 827 OCR-описаний в день. Теперь 0 — OpenRouter даёт rate limit с первой же позиции в очереди. Один мем (#6549510) застрял во главе и блокирует весь батч. Бэклог растёт второй день подряд.

FFM-492 у CTO. Либо баланс OpenRouter ушёл в минус, либо застрявший мем надо просто пропустить.

GOAT recency filter — День 3/14. Никаких регрессий: continuation rate 97.8%, LR на baseline 39.4%, session length ~30. Следим до 27 апреля.

Новый баг: 3 ошибки загрузки — "File must be non-empty". Что-то отправляет пустые файлы в стораж.

Prefect flows — all completed. Вебхук живой. Мемы доходят. Система работает, просто описания к ним временно не генерируются.

Два тикета в очереди. Едем дальше.

↳ @ffmemesbot

---

## Key Metrics Referenced

| Metric | Value |
|--------|-------|
| describe_memes (24h) | 0/batch (24h+ degraded) |
| OCR baseline | 827/day |
| Open issues | FFM-492 (describe_memes), upload errors (3x) |
| GOAT LR baseline | 39.4% |
| GOAT continuation rate | 97.8% |
| Session length (NS) | ~30 |
| WAU | ~676 |
| Experiment day | 3/14 (measuring until Apr 27) |
| Prefect flows | all completed |
| Webhook | online |

## Visual

Stat card (1500x1000, matplotlib, brand palette #FF6B35 / #1A1A2E):
- Header: @ffmemes · build in public · 16 апреля 2026 | GOAT experiment · День 3/14
- Left: System health (Prefect, webhook, ok_pct, reactions, containers — all green dots)
- Left below: GOAT experiment progress bar (3/14), baseline metrics table
- Right top: describe_memes alert box (red border — 0 described 24h+, meme #6549510, FFM-492)
- Right mid: Upload errors card (yellow border — 3x "File must be non-empty")
- Right below: Scale panels (535K memes, 22M+ reactions, 22K users, 9 engines)
- Footer: "Задеплоили. Нашли баги. Честно рассказываем." / ↳ @ffmemesbot

## Narrative

Build-in-public story: describe_memes has been down for 24h+ (was "just broke" yesterday, now second day running at 0/batch). OCR backlog growing. CTO has FFM-492. GOAT recency filter Day 3/14 — holding baseline, no regressions. New upload error bug caught (empty files). Product is alive but two bugs in the queue.
