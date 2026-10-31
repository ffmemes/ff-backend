---
id: ocr_dedup_watermark_fix
status: shipped
hypothesis: OCR duplicate merges that share only the watermark are false; stripping it and requiring similarity >=0.6 removes them
primary_metric: false-merge rate on hand-labelled OCR merges
guardrails: recall of true merges, lookup latency
unit: meme
variants: none (fix)
started: 2026-10-31
check_on: 
decided: 2026-10-31
result: false merges 43% to 2.5% at 93.5% recall (152 labelled merges, 60 days); 7,762 false-merged memes restored to ok
learning: Watermark text made unrelated short captions look identical, and hub originals absorbed hundreds of dupes; strip boilerplate before text similarity
code: find_duplicate_by_ocr_text, OCR_WATERMARK_PATTERN (PRs #380, #382)
readout: docs/analyst/data/2026-10-31-dedup-restored-meme-ids.txt
---

# Fix: OCR dedup watermark (not an experiment, kept for the learning)

PR #380 (2026-10-31): OCR duplicate matching strips the `@ffmemesbot` watermark (and
misreads) and `imgflip.com`, requires `similarity >= 0.6` (the `%` operator stays only
as the index prefilter), and picks the most similar candidate first.

Why: of 152 hand-labelled OCR merges from the last 60 days, 43% were false, mostly
unrelated short captions that shared only the watermark. Published-first ordering
funnelled them into hub originals: one meme whose whole text is the watermark
absorbed 655 dupes, another 760. In the last 24h before the fix, 259 of 565 merges
were below the new rule.

| rule | false merges | recall of true merges |
|---|---|---|
| raw text, similarity 0.3 | 43% | 100% (by definition) |
| stripped, similarity >= 0.6 | 2.5% | 93.5% |

PR #382: narrowed the watermark regex (the old `\S*` removed caption words glued to
the watermark) and reused it in the `has_text` check.

Restore (2026-10-31 14:40 UTC): 7,762 false-merged memes went back to `ok`
(ids: [`docs/analyst/data/2026-10-31-dedup-restored-meme-ids.txt`](../docs/analyst/data/2026-10-31-dedup-restored-meme-ids.txt)).
This is a confound for [explore_budget_v1](2026-10-30-explore-budget.md).
