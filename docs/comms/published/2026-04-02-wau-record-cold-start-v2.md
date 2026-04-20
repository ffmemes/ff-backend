# Daily Post — 2026-04-02

**Channel:** @ffmemes (chat_id=-1001472939243)
**Message ID:** 201
**Status:** Published ✅
**Source data:** experiments/reports/analyst-2026-04-01.md + experiments/log.jsonl

---

## Post Text (Russian, HTML parse mode)

658 WAU. Рекорд без рекламы.

Семь дней экспериментов, три инцидента с базой, пять фиксов — и аудитория выросла на +17 за неделю. Что происходит под капотом:

▪ **cold_start v2, день 7 из 14.** Новые юзеры первые мемы теперь видят из «золотого фонда» — 104к мемов с LR ≥ 40%. Результат: первый мем лайкают в 55.6% случаев. Это *самый высокий LR из всех 9 движков*. Хорошая выборка пока бьёт персонализацию.

▪ **База данных трещала три дня.** Дедлоки на UPDATE, full-table scan-ы в статистике, гонки условий. Зашипили 5 фиксов подряд прямо в прод через Claude Code.

▪ **A/B «загрузи мем».** После 10-го мема новым юзерам предлагаем загрузить свой. Пока: тест-группа — 10% загрузок, контроль — 0%. Выборка маленькая, но направление норм.

🟥 North Star просел 18 → 17. Мусорный хвост: 95 юзеров с мартовского спайка почти всё ушли — на 5-й день остался 1 человек из 95. К 3 апреля метрика вернётся.

WAU 658, эксперимент на треке, база стабильна.

↳ @ffmemesbot — сам бот

~ @danokhlopkov ~

---

## Key Metrics Referenced

| Metric | Value |
|--------|-------|
| WAU | 658 (all-time high) |
| North Star | 17 (target ≥16, transient dip) |
| cold_start_explore LR | 55.6% (highest of 9 engines) |
| cold_start_explore pool | 104k memes |
| DB fixes shipped | 5 (deadlocks, full-table scans) |
| Upload promo treatment | 10% upload rate vs 0% control |
| cold_start_v2 day | 7/14 (concludes Apr 9) |
