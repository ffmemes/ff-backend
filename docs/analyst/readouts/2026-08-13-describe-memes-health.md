# Describe Memes health — 2026-08-13

Snapshot via `psql "$ANALYST_DATABASE_URL"` and
[`docs/analyst/describe-memes-health.sql`](../describe-memes-health.sql).

## Verdict

**Pipeline is not fully dead, but throughput is ~1% of design target.**

| Metric | Value | Design target |
|--------|-------|---------------|
| OK image memes | ~241k | — |
| With OpenRouter `description` | ~18.9k (**7.8%**) | high coverage over time |
| Described last 24h | **~11** | up to **864**/day scheduled |
| Described last 7d | **~74** | ~6k |
| Eligible backlog (no description, failures &lt; 3) | **~222k** | shrinking |
| Permanently failed (failures ≥ 3) | ~528 | — |
| Latest `calculated_at` | 2026-08-13 ~06:30 UTC | should advance every 15m when free tier allows |

Daily successful descriptions over the last two weeks stay in the **~3–15/day**
band (not zero). Something is still writing OCR occasionally.

## Failure shape

`describe_failures` / `last_failure_reason` on ok images:

| Reason | Count (approx) |
|--------|----------------|
| `all models failed` | ~2270 |
| `per-meme timeout (120s)` | ~196 |
| `Timed out` | ~36 |

Recent successful model mix (30d, rows with description): mostly
`nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`, some Gemma 4 free variants.

## Legacy OCR noise

~55k ok images have `calculated_at` but **no** `description`. Spot checks show
legacy **`easyocr`** payloads (`model: easyocr`, text only). Product dedup /
search that require `description` treat these as **not described**.
`get_memes_to_describe` correctly keys off missing `description`.

## Interpretation

1. **Not paused into total silence** — occasional successes prove download +
   OpenRouter path still works sometimes.
2. **Severe free-tier backpressure / model flakiness** — design assumes 900
   free attempts/day; observed successful descriptions are ~10/day, consistent
   with near-constant 429 / all-models-failed / timeout windows documented in
   [`specs/describe-memes.md`](../../../specs/describe-memes.md).
3. **Backlog will not clear** at current rate (~220k / 10 per day ≈ decades).
4. Dedup and OCR-aware ranking only see the ~8% with full vision descriptions
   (plus any text-only legacy easyocr rows for text search).

## Follow-ups (ops, not done in this PR)

1. Prefect: check whether `Describe Memes (OpenRouter)` runs are Completed vs
   short-circuited on quota/rate-limit (flow logs: `rate_limited`,
   `daily_budget_exhausted`, key health).
2. OpenRouter dashboard: free-model daily remaining, key limit, balance ≥ $0,
   lifetime purchase tier ($10+ → 1000 free req/day vs 50).
3. Redis: `openrouter:free_requests:YYYY-MM-DD`, model cooldown keys.
4. If free tier is stuck at 50/day, expect ~dozens of attempts and few
   successes — matches this readout; paid models remain **forbidden**.
5. Optional product: re-describe high-`nlikes` easyocr-only memes to fill
   `description` for dedup (priority already likes-desc after uploads).

## Related

- Flow: [`src/flows/storage/describe_memes.py`](../../../src/flows/storage/describe_memes.py)
- Spec: [`specs/describe-memes.md`](../../../specs/describe-memes.md)
- Agent inspect API (media + OCR card): [`docs/admin-meme-inspect.md`](../../admin-meme-inspect.md)
