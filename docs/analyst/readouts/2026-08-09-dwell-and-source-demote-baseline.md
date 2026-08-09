# Baseline: dwell + source demote (2026-08-09)

Pre-merge baseline for PR #340 (soft demote + `broadcast_reengagement` label).
Queries: `docs/analyst/dwell-feed-vs-broadcast.sql`,
`docs/analyst/source-affinity-demote-guardrails.sql`.

## Feed `sec_to_react` (7d, non-broadcast)

| reaction | n | p25 | p50 | p75 | % >1h |
|----------|------|------|------|------|-------|
| like | 48 616 | 3.63s | **7.10s** | 14.68s | 1.9% |
| skip | 98 374 | 2.40s | **4.74s** | 9.74s | 1.5% |

Skip is faster than like (~2.4s p50 gap) — consistent with “next” not “hate”.
Stale reactions (>1h) are rare (~1.5–2%); safe to exclude from affinity scoring later.

## Dwell buckets (7d, feed)

| bucket | like % | skip % |
|--------|--------|--------|
| instant &lt;2s | 9.1 | **19.4** |
| quick 2–15s | 66.5 | 65.6 |
| engaged 15–60s | 17.3 | 10.4 |
| long 1m–1h | 5.2 | 3.2 |
| stale &gt;1h | 1.9 | 1.5 |

Instant skips are ~2× instant likes → strongest “didn’t bother” signal, not source ban.

## Inventory risk if hard-block majority-dislike

Active users 7d: **380**

| metric | value |
|--------|-------|
| avg sources touched | 395 |
| avg majority-dislike sources (n≥5) | **114** (~24% of sources) |
| avg strong-hate sources (3×, n≥15) | 57 |

Hard majority-block would gut inventory for typical active users → empty queue risk.
Soft demote (×0.15) keeps candidates; strong-hate hard-block stays **OFF** by default.

## 24h volume baseline (pre-deploy)

| metric | value |
|--------|-------|
| sends | 23 130 |
| users | 335 |
| reactions | 22 114 |
| like rate | 29.1% |
| `broadcast*` labeled | **0** (label not live yet) |

Top engines 24h: `low_sent_pool`, `lr_smoothed`, `recently_liked`, `best_uploaded_memes`, `es_ranked`.

## Post-deploy checks

After Coolify deploys `production` with #340:

1. Re-run section 6 of dwell SQL — expect `broadcast_reengagement` rows after next retention push.
2. Re-run guardrails — hourly sends/LR should not cliff; engine mix stays multi-engine.
3. Optional: Sentry for empty-queue alert spam (`user_id: … has empty meme queue`).
